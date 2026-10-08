package main

import (
	"context"
	"encoding/json"
	"math"
	"net/http"
	"net/http/httptest"
	"testing"
	"time"
)

func TestIdleSeconds(t *testing.T) {
	cases := []struct {
		name             string
		tick, last, want uint32
	}{
		{"just touched", 5000, 5000, 0},
		{"rounds down", 5999, 2000, 3},
		{"tick counter wrapped after 49.7 days", 1000, math.MaxUint32 - 999, 2},
	}
	for _, c := range cases {
		if got := idleSeconds(c.tick, c.last); got != c.want {
			t.Errorf("%s: idleSeconds(%d, %d) = %d, want %d", c.name, c.tick, c.last, got, c.want)
		}
	}
}

func TestClampInterval(t *testing.T) {
	cases := map[int]time.Duration{
		-5: 30 * time.Second, 0: 30 * time.Second, 29: 30 * time.Second,
		60: time.Minute, 3600: time.Hour, 99999: time.Hour,
	}
	for in, want := range cases {
		if got := clampInterval(in); got != want {
			t.Errorf("clampInterval(%d) = %v, want %v", in, got, want)
		}
	}
}

func TestPadActive(t *testing.T) {
	cases := []struct {
		name string
		s    padState
		want bool
	}{
		{"resting", padState{}, false},
		{"stick drift inside deadzone", padState{LX: 7000, LY: -7000, RX: 8000, RY: -8000}, false},
		{"light trigger noise", padState{LeftTrigger: 30}, false},
		{"button held", padState{Buttons: 0x1000}, true},
		{"left stick pushed", padState{LX: 7850}, true},
		{"right stick pushed fully left", padState{RX: math.MinInt16}, true},
		{"trigger pressed", padState{RightTrigger: 31}, true},
	}
	for _, c := range cases {
		if got := c.s.active(); got != c.want {
			t.Errorf("%s: active() = %v, want %v", c.name, got, c.want)
		}
	}
}

func TestGamepadsTrackInput(t *testing.T) {
	t0 := time.Date(2026, 10, 1, 12, 0, 0, 0, time.UTC)
	var g gamepads
	if _, ok := g.idleSince(t0); ok {
		t.Fatal("no controller input yet")
	}
	g.observe(0, t0, padState{}, true) // plugged in, resting
	if _, ok := g.idleSince(t0); ok {
		t.Fatal("a resting controller is not input")
	}
	g.observe(0, t0.Add(5*time.Second), padState{Buttons: 1}, true) // pressed
	g.observe(0, t0.Add(10*time.Second), padState{}, true)          // released: a change counts too
	if s, ok := g.idleSince(t0.Add(70 * time.Second)); !ok || s != 60 {
		t.Errorf("idleSince = %d, %v; want 60, true", s, ok)
	}
}

func TestEmptySlotsProbedOncePerMinute(t *testing.T) {
	t0 := time.Date(2026, 10, 1, 12, 0, 0, 0, time.UTC)
	var g gamepads
	if !g.due(1, t0) {
		t.Fatal("a never-probed slot must be due")
	}
	g.observe(1, t0, padState{}, false) // nothing plugged in
	if g.due(1, t0.Add(59*time.Second)) {
		t.Error("empty slot re-probed too soon")
	}
	if !g.due(1, t0.Add(time.Minute)) {
		t.Error("empty slot not re-probed after a minute")
	}
	g.observe(1, t0.Add(time.Minute), padState{}, true) // plugged in
	if !g.due(1, t0.Add(time.Minute+5*time.Second)) {
		t.Error("a connected slot must be polled every time")
	}
}

func TestIdleNowUsesControllerInput(t *testing.T) {
	g := &gamepads{}
	g.observe(0, time.Now().Add(-3*time.Second), padState{Buttons: 1}, true)
	if idle := (&agent{pads: g}).idleNow(); idle > 3 {
		t.Errorf("idleNow() = %d, want <= 3 right after controller input", idle)
	}
}

func TestSendPostsHeartbeatAndReadsReply(t *testing.T) {
	var got payload
	var auth string
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		auth = r.Header.Get("Authorization")
		json.NewDecoder(r.Body).Decode(&got)
		w.Write([]byte(`{"interval": 120, "enabled": false}`))
	}))
	defer srv.Close()

	a := &agent{url: srv.URL, token: "secret", client: srv.Client(),
		base: payload{PC: "PC07", BootID: "b1", AgentVersion: "test"}}
	r, err := a.send(context.Background(), "boot")
	if err != nil {
		t.Fatal(err)
	}
	if auth != "Bearer secret" || got.PC != "PC07" || got.Event != "boot" || got.BootID != "b1" {
		t.Errorf("server received auth=%q payload=%+v", auth, got)
	}
	if r.Interval != 120 || r.Enabled {
		t.Errorf("reply = %+v, want interval 120, enabled false", r)
	}
}

func TestSendDefaultsMissingReplyFields(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) { w.Write([]byte(`{}`)) }))
	defer srv.Close()
	r, err := (&agent{url: srv.URL, client: srv.Client()}).send(context.Background(), "heartbeat")
	if err != nil || r.Interval != 60 || !r.Enabled {
		t.Errorf("reply = %+v, err = %v; want interval 60, enabled true", r, err)
	}
}

func TestSendTreatsNon200AsError(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		http.Error(w, "no", http.StatusUnauthorized)
	}))
	defer srv.Close()
	if _, err := (&agent{url: srv.URL, client: srv.Client()}).send(context.Background(), "heartbeat"); err == nil {
		t.Fatal("want an error for a 401 reply")
	}
}
