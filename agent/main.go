// Command cafe-agent reports "seconds since last keyboard, mouse or controller input"
// to the café status server: a boot event, a heartbeat every interval, and a shutdown
// event (first_milestone.md §5). Report-only: no hooks, no disk writes, and it runs in
// Windows background mode so games keep the CPU, disk and memory.
package main

import (
	"bytes"
	"context"
	"crypto/rand"
	"encoding/hex"
	"encoding/json"
	"flag"
	"fmt"
	"io"
	mrand "math/rand/v2"
	"net"
	"net/http"
	"os"
	"runtime"
	"strings"
	"sync"
	"syscall"
	"time"
	"unsafe"
)

// Defaults, overridable at build time:
//
//	go build -ldflags "-X main.serverURL=https://... -X main.token=... -X main.version=1.0.0"
var (
	serverURL = "http://localhost:8000/api/v1/heartbeat"
	token     = ""
	version   = "dev"
)

var (
	user32   = syscall.NewLazyDLL("user32.dll")
	kernel32 = syscall.NewLazyDLL("kernel32.dll")
	xinput   = syscall.NewLazyDLL("xinput1_4.dll")

	procGetLastInputInfo  = user32.NewProc("GetLastInputInfo")
	procRegisterClassExW  = user32.NewProc("RegisterClassExW")
	procCreateWindowExW   = user32.NewProc("CreateWindowExW")
	procDefWindowProcW    = user32.NewProc("DefWindowProcW")
	procGetMessageW       = user32.NewProc("GetMessageW")
	procDispatchMessageW  = user32.NewProc("DispatchMessageW")
	procGetTickCount      = kernel32.NewProc("GetTickCount")
	procGetTickCount64    = kernel32.NewProc("GetTickCount64")
	procGetCurrentProcess = kernel32.NewProc("GetCurrentProcess")
	procSetPriorityClass  = kernel32.NewProc("SetPriorityClass")
	procGetModuleHandleW  = kernel32.NewProc("GetModuleHandleW")
	procXInputGetState    = xinput.NewProc("XInputGetState")
)

const (
	processModeBackgroundBegin = 0x00100000 // low CPU, I/O and memory priority
	wmQueryEndSession          = 0x0011
	wmEndSession               = 0x0016

	// Deadzones recommended by Microsoft (XInput.h); stick drift stays inside them.
	leftStickDeadzone  = 7849
	rightStickDeadzone = 8689
	triggerThreshold   = 30
)

type payload struct {
	PC           string `json:"pc"`
	MAC          string `json:"mac"`
	Event        string `json:"event"`
	IdleS        uint32 `json:"idle_s"`
	BootID       string `json:"boot_id"`
	UptimeS      uint64 `json:"uptime_s"`
	AgentVersion string `json:"agent_version"`
}

type reply struct {
	Interval int  `json:"interval"`
	Enabled  bool `json:"enabled"`
}

type agent struct {
	url, token string
	client     *http.Client
	pads       *gamepads // nil when XInput isn't available
	base       payload   // the fields that never change while running
}

// idleSeconds is correct across the 49.7-day wrap of the 32-bit tick counter.
func idleSeconds(tickMs, lastInputMs uint32) uint32 { return (tickMs - lastInputMs) / 1000 }

// clampInterval keeps a server-sent interval within 30 s – 1 h.
func clampInterval(seconds int) time.Duration {
	return time.Duration(min(max(seconds, 30), 3600)) * time.Second
}

// padState is XINPUT_GAMEPAD: the part of a controller's state that shows a person is playing.
type padState struct {
	Buttons                   uint16
	LeftTrigger, RightTrigger uint8
	LX, LY, RX, RY            int16
}

func outside(x, y int16, deadzone int32) bool {
	ax, ay := int32(x), int32(y)
	return ax > deadzone || ax < -deadzone || ay > deadzone || ay < -deadzone
}

// active: a button held, a trigger pressed, or a stick pushed past its deadzone.
func (s padState) active() bool {
	return s.Buttons != 0 || s.LeftTrigger > triggerThreshold || s.RightTrigger > triggerThreshold ||
		outside(s.LX, s.LY, leftStickDeadzone) || outside(s.RX, s.RY, rightStickDeadzone)
}

// gamepads remembers when a controller was last used. Windows' input counter ignores
// XInput controllers, so without this a controller-only player would look Idle.
// Polled from one goroutine and read from another, hence the mutex.
type gamepads struct {
	mu        sync.Mutex
	prev      [4]padState
	connected [4]bool
	nextProbe [4]time.Time
	lastInput time.Time
}

// due reports whether slot i should be polled now: connected slots every time,
// empty slots once a minute (probing an unplugged slot is slow).
func (g *gamepads) due(i int, now time.Time) bool {
	g.mu.Lock()
	defer g.mu.Unlock()
	return g.connected[i] || !now.Before(g.nextProbe[i])
}

// observe records one poll of slot i; ok is false when nothing is plugged in.
func (g *gamepads) observe(i int, now time.Time, s padState, ok bool) {
	g.mu.Lock()
	defer g.mu.Unlock()
	if !ok {
		g.connected[i], g.nextProbe[i] = false, now.Add(time.Minute)
		return
	}
	if s.active() || (g.connected[i] && s.Buttons != g.prev[i].Buttons) {
		g.lastInput = now
	}
	g.connected[i], g.prev[i] = true, s
}

// idleSince is whole seconds since the last controller input, if there was any.
func (g *gamepads) idleSince(now time.Time) (uint32, bool) {
	g.mu.Lock()
	defer g.mu.Unlock()
	if g.lastInput.IsZero() {
		return 0, false
	}
	return uint32(now.Sub(g.lastInput) / time.Second), true
}

// readPad polls controller slot i (0-3) through XInputGetState.
func readPad(i int) (padState, bool) {
	var st struct { // XINPUT_STATE
		packet uint32
		pad    padState
	}
	r, _, _ := procXInputGetState.Call(uintptr(i), uintptr(unsafe.Pointer(&st)))
	return st.pad, r == 0 // 0 = ERROR_SUCCESS; anything else = not connected
}

// pollGamepads checks controllers 0-3 every 5 s, forever.
// ponytail: sampling, so a tap released between two samples is missed; real play
// holds sticks and triggers. Poll faster only if Phase 2 shows false Idles.
func pollGamepads(g *gamepads) {
	for {
		now := time.Now()
		for i := 0; i < 4; i++ {
			if g.due(i, now) {
				s, ok := readPad(i)
				g.observe(i, now, s, ok)
			}
		}
		time.Sleep(5 * time.Second)
	}
}

func currentIdleSeconds() uint32 {
	info := struct{ cbSize, dwTime uint32 }{cbSize: 8} // LASTINPUTINFO
	procGetLastInputInfo.Call(uintptr(unsafe.Pointer(&info)))
	tick, _, _ := procGetTickCount.Call()
	return idleSeconds(uint32(tick), info.dwTime)
}

// idleNow is the time since the latest keyboard, mouse or controller input.
func (a *agent) idleNow() uint32 {
	idle := currentIdleSeconds()
	if a.pads != nil {
		if s, ok := a.pads.idleSince(time.Now()); ok && s < idle {
			idle = s
		}
	}
	return idle
}

func uptimeSeconds() uint64 {
	ms, _, _ := procGetTickCount64.Call()
	return uint64(ms) / 1000
}

func enterBackgroundMode() {
	self, _, _ := procGetCurrentProcess.Call()
	procSetPriorityClass.Call(self, processModeBackgroundBegin)
}

func newBootID() string {
	b := make([]byte, 8)
	rand.Read(b)
	return hex.EncodeToString(b)
}

// primaryMAC is the MAC of the first up, non-loopback interface with an IPv4 address.
func primaryMAC() string {
	ifaces, _ := net.Interfaces()
	for _, i := range ifaces {
		if i.Flags&net.FlagUp == 0 || i.Flags&net.FlagLoopback != 0 || len(i.HardwareAddr) != 6 {
			continue
		}
		addrs, _ := i.Addrs()
		for _, a := range addrs {
			if ip, ok := a.(*net.IPNet); ok && ip.IP.To4() != nil {
				return strings.ToUpper(i.HardwareAddr.String())
			}
		}
	}
	return ""
}

// send posts one event and returns the server's reply. ctx bounds how long it may take.
func (a *agent) send(ctx context.Context, event string) (reply, error) {
	p := a.base
	p.Event = event
	p.IdleS = a.idleNow()
	p.UptimeS = uptimeSeconds()
	body, err := json.Marshal(p)
	if err != nil {
		return reply{}, err
	}
	req, err := http.NewRequestWithContext(ctx, http.MethodPost, a.url, bytes.NewReader(body))
	if err != nil {
		return reply{}, err
	}
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("Authorization", "Bearer "+a.token)
	resp, err := a.client.Do(req)
	if err != nil {
		return reply{}, err
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		return reply{}, fmt.Errorf("server replied %s", resp.Status)
	}
	r := reply{Interval: 60, Enabled: true} // kept if the server omits a field
	err = json.NewDecoder(io.LimitReader(resp.Body, 4096)).Decode(&r)
	return r, err
}

type wndClassEx struct { // WNDCLASSEXW
	cbSize        uint32
	style         uint32
	lpfnWndProc   uintptr
	cbClsExtra    int32
	cbWndExtra    int32
	hInstance     uintptr
	hIcon         uintptr
	hCursor       uintptr
	hbrBackground uintptr
	lpszMenuName  *uint16
	lpszClassName *uint16
	hIconSm       uintptr
}

type winMsg struct { // MSG
	hwnd     uintptr
	message  uint32
	wParam   uintptr
	lParam   uintptr
	time     uint32
	pt       struct{ x, y int32 }
	lPrivate uint32
}

// watchSessionEnd runs a hidden top-level window and calls onEnd when Windows shuts
// down or logs off. It must be top-level: message-only windows don't get WM_ENDSESSION.
// (SetConsoleCtrlHandler is no alternative: programs with a window never receive
// console shutdown signals.)
func watchSessionEnd(onEnd func()) {
	runtime.LockOSThread() // a window's messages arrive on the thread that created it
	className, _ := syscall.UTF16PtrFromString("CafeAgentWindow")
	instance, _, _ := procGetModuleHandleW.Call(0)
	wndProc := syscall.NewCallback(func(hwnd, msg, wParam, lParam uintptr) uintptr {
		switch msg {
		case wmQueryEndSession:
			return 1 // never block a shutdown
		case wmEndSession:
			if wParam != 0 {
				onEnd()
			}
			return 0
		}
		r, _, _ := procDefWindowProcW.Call(hwnd, msg, wParam, lParam)
		return r
	})
	wc := wndClassEx{lpfnWndProc: wndProc, hInstance: instance, lpszClassName: className}
	wc.cbSize = uint32(unsafe.Sizeof(wc))
	procRegisterClassExW.Call(uintptr(unsafe.Pointer(&wc)))
	procCreateWindowExW.Call(0, uintptr(unsafe.Pointer(className)), 0, 0, 0, 0, 0, 0, 0, 0, instance, 0)
	var m winMsg
	for {
		r, _, _ := procGetMessageW.Call(uintptr(unsafe.Pointer(&m)), 0, 0, 0)
		if int32(r) <= 0 {
			return
		}
		procDispatchMessageW.Call(uintptr(unsafe.Pointer(&m)))
	}
}

func main() {
	url := flag.String("url", serverURL, "heartbeat endpoint")
	tok := flag.String("token", token, "agent token")
	flag.Parse()

	enterBackgroundMode()
	host, _ := os.Hostname()
	a := &agent{url: *url, token: *tok, client: &http.Client{}, base: payload{
		PC: host, MAC: primaryMAC(), BootID: newBootID(), AgentVersion: version,
	}}
	if procXInputGetState.Find() == nil { // xinput1_4.dll ships with Windows 8 and later
		a.pads = &gamepads{}
		go pollGamepads(a.pads)
	}

	// The shutdown message reuses a.client's open connection: no new TLS handshake
	// while Windows is shutting down. If it is lost, silence still marks the PC Off.
	go watchSessionEnd(func() {
		ctx, cancel := context.WithTimeout(context.Background(), 2*time.Second)
		defer cancel()
		a.send(ctx, "shutdown")
	})

	// Spread the first report so 30 PCs switched on together don't arrive in the same second.
	time.Sleep(time.Duration(mrand.IntN(31)) * time.Second)

	event := "boot"
	for {
		interval := time.Minute
		ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
		r, err := a.send(ctx, event)
		cancel()
		if err == nil {
			if !r.Enabled {
				return // remote off switch: stay quiet until the next boot
			}
			interval = clampInterval(r.Interval)
		} // on error: drop it and try again next tick (no queue, nothing on disk)
		event = "heartbeat"
		time.Sleep(interval)
	}
}
