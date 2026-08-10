// Package main implements the Norma calibration workload binary.
//
// This is a single static HTTP server (CGO_ENABLED=0) that provides health,
// version, readiness, metrics, and health-toggle endpoints for the norma-k8s
// Juju charm's Pebble-managed workload.
package main

import (
	"encoding/json"
	"flag"
	"fmt"
	"net/http"
	"os"
	"strconv"
	"sync/atomic"

	"github.com/prometheus/client_golang/prometheus"
	"github.com/prometheus/client_golang/prometheus/promhttp"
)

// version is set at build time via ldflags: -X main.version=X.Y.Z
var version = "dev"

// healthFlagFile is the path to the flag file whose existence indicates
// unhealthy state. Defaults to /tmp/norma-unhealthy; overridden by the
// HEALTH_FLAG_FILE environment variable.
//
// The flag file is the SINGLE source of truth for health. It used to be ANDed
// with an in-memory atomic bool, which wedged the workload permanently
// unhealthy: POST /toggle-health flipped both signals in opposite directions,
// so once they desynchronised the AND could never be true again. That state was
// reachable two ways in normal operation — the charm's toggle-health action
// writes this file directly (never touching the bool), and a pod restart with
// the file present starts the process desynchronised. A file is also the only
// signal that survives a restart and is visible to both the charm and the
// workload, so it is the correct one to keep.
var healthFlagFile string

// lastObservedHealthy backs the sampled transition counter: -1 = not yet
// observed, 0 = unhealthy, 1 = healthy.
var lastObservedHealthy atomic.Int32

// ---------- Prometheus metrics ----------

var (
	httpRequestsTotal = prometheus.NewCounterVec(
		prometheus.CounterOpts{
			Name: "norma_http_requests_total",
			Help: "Total number of HTTP requests handled by the norma workload.",
		},
		[]string{"method", "path", "status"},
	)

	// Sampled, not exact: health can change out-of-process (the charm's
	// toggle-health action writes the flag file directly), so transitions are
	// counted when observed — on scrape and on POST /toggle-health. Two flips
	// between observations therefore count as none. Exactness would require
	// watching the file, which is not worth an inotify dependency here.
	healthTogglesTotal = prometheus.NewCounter(
		prometheus.CounterOpts{
			Name: "norma_health_toggles_total",
			Help: "Observed health state transitions (sampled at scrape and on toggle).",
		},
	)

	// GaugeFunc, not Gauge: evaluated at scrape time, so it reflects health
	// however it was changed. A plain Gauge was only ever Set() from main() and
	// the HTTP toggle handler, which meant the charm's toggle-health action (a
	// direct flag-file write over Pebble) never moved it — and the shipped alert
	// `norma_healthy == 0` could therefore never fire.
	healthyGauge = prometheus.NewGaugeFunc(
		prometheus.GaugeOpts{
			Name: "norma_healthy",
			Help: "Whether the workload considers itself healthy (1) or not (0).",
		},
		func() float64 {
			if observeHealth() {
				return 1
			}
			return 0
		},
	)
)

func init() {
	lastObservedHealthy.Store(-1) // "not yet observed" — avoids a bogus first transition
	prometheus.MustRegister(httpRequestsTotal)
	prometheus.MustRegister(healthTogglesTotal)
	prometheus.MustRegister(healthyGauge)
}

// ---------- HTTP handlers ----------

// handleHealth returns 200 "OK" when healthy, 500 "UNHEALTHY" otherwise.
// Healthy means the health flag file does not exist — see healthFlagFile.
func handleHealth(w http.ResponseWriter, r *http.Request) {
	if isHealthy() {
		w.WriteHeader(http.StatusOK)
		fmt.Fprint(w, "OK")
	} else {
		w.WriteHeader(http.StatusInternalServerError)
		fmt.Fprint(w, "UNHEALTHY")
	}
}

// handleVersion returns the build version as JSON.
func handleVersion(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(http.StatusOK)
	_ = json.NewEncoder(w).Encode(map[string]string{"version": version})
}

// handleReady always returns 200 "READY".
func handleReady(w http.ResponseWriter, r *http.Request) {
	w.WriteHeader(http.StatusOK)
	fmt.Fprint(w, "READY")
}

// handleToggleHealth toggles the health flag file (create if absent, remove if
// present) and returns JSON with the previous and current health states.
//
// It deliberately drives the SAME signal the charm's toggle-health action
// drives, so the two paths agree and either can undo the other. The gauge needs
// no update here: it is a GaugeFunc evaluated at scrape time.
func handleToggleHealth(w http.ResponseWriter, r *http.Request) {
	prevHealthy := isHealthy()
	toggleFlagFile()
	nowHealthy := observeHealth() // records the transition we just caused

	prev := healthString(prevHealthy)
	cur := healthString(nowHealthy)

	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(http.StatusOK)
	_ = json.NewEncoder(w).Encode(map[string]string{
		"previous": prev,
		"current":  cur,
	})
}

// ---------- helpers ----------

// isHealthy reports health from the single source of truth: the workload is
// healthy exactly when the flag file does not exist. Pure — no side effects.
func isHealthy() bool {
	return !flagFileExists()
}

// observeHealth reads health and records a transition against the previous
// observation. Used where sampling is meaningful (scrape, toggle) so that
// out-of-process changes — the charm writing the flag file over Pebble — are
// still counted. See healthTogglesTotal for the sampling caveat.
func observeHealth() bool {
	h := isHealthy()
	var cur int32
	if h {
		cur = 1
	}
	if prev := lastObservedHealthy.Swap(cur); prev >= 0 && prev != cur {
		healthTogglesTotal.Inc()
	}
	return h
}

// flagFileExists returns true if the health flag file exists on disk.
func flagFileExists() bool {
	_, err := os.Stat(healthFlagFile)
	return err == nil
}

// toggleFlagFile creates the flag file if it does not exist, or removes it
// if it does.
func toggleFlagFile() {
	if flagFileExists() {
		_ = os.Remove(healthFlagFile)
	} else {
		_ = os.WriteFile(healthFlagFile, []byte("unhealthy"), 0644)
	}
}

// healthString returns "healthy" or "unhealthy".
func healthString(h bool) string {
	if h {
		return "healthy"
	}
	return "unhealthy"
}

// instrumentHandler wraps an http.Handler to record request metrics.
func instrumentHandler(path string, next http.HandlerFunc) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		rec := &statusRecorder{ResponseWriter: w, statusCode: http.StatusOK}
		next.ServeHTTP(rec, r)
		httpRequestsTotal.WithLabelValues(r.Method, path, strconv.Itoa(rec.statusCode)).Inc()
	}
}

// statusRecorder wraps http.ResponseWriter to capture the status code.
type statusRecorder struct {
	http.ResponseWriter
	statusCode int
}

func (sr *statusRecorder) WriteHeader(code int) {
	sr.statusCode = code
	sr.ResponseWriter.WriteHeader(code)
}

// ---------- self-check (--check mode) ----------

// runCheck makes an HTTP GET to http://localhost:<port>/health and exits 0 if
// healthy (2xx), 1 otherwise. This is used by Pebble exec health checks.
func runCheck(port int) {
	url := fmt.Sprintf("http://localhost:%d/health", port)
	resp, err := http.Get(url) //nolint:gosec // localhost only
	if err != nil {
		os.Exit(1)
	}
	defer resp.Body.Close()
	if resp.StatusCode == http.StatusOK {
		os.Exit(0)
	}
	os.Exit(1)
}

// ---------- main ----------

func main() {
	// Resolve the health flag file path.
	healthFlagFile = os.Getenv("HEALTH_FLAG_FILE")
	if healthFlagFile == "" {
		healthFlagFile = "/tmp/norma-unhealthy"
	}

	// Determine default port from PORT env var, falling back to 8080.
	defaultPort := 8080
	if envPort := os.Getenv("PORT"); envPort != "" {
		if p, err := strconv.Atoi(envPort); err == nil && p > 0 {
			defaultPort = p
		}
	}

	port := flag.Int("port", defaultPort, "HTTP listen port")
	check := flag.Bool("check", false, "Run health check against own /health endpoint and exit")
	showVersion := flag.Bool("version", false, "Print the build version and exit")
	flag.Parse()

	// --version mode: print the version baked in at link time and exit. The
	// charm's get-version action execs this to identify exactly which workload
	// image (OCI resource revision) is running — the env-injected VERSION is the
	// charm's version, which does not change on a `refresh --resource` image swap.
	if *showVersion {
		fmt.Println(version)
		return
	}

	// --check mode: probe and exit.
	if *check {
		runCheck(*port)
		return // unreachable; runCheck calls os.Exit
	}

	// No health state to initialise: the flag file IS the state, so the workload
	// comes up matching whatever the charm last set — including across a pod
	// restart, which the previous in-memory bool got wrong.

	// Build the mux using Go 1.22+ method-pattern routing.
	mux := http.NewServeMux()
	mux.HandleFunc("GET /health", instrumentHandler("/health", handleHealth))
	mux.HandleFunc("GET /version", instrumentHandler("/version", handleVersion))
	mux.HandleFunc("GET /ready", instrumentHandler("/ready", handleReady))
	mux.HandleFunc("POST /toggle-health", instrumentHandler("/toggle-health", handleToggleHealth))

	// /metrics is served by promhttp and also instrumented.
	metricsHandler := promhttp.Handler()
	mux.HandleFunc("GET /metrics", instrumentHandler("/metrics", func(w http.ResponseWriter, r *http.Request) {
		metricsHandler.ServeHTTP(w, r)
	}))

	addr := fmt.Sprintf(":%d", *port)
	fmt.Printf("norma workload listening on %s (version %s)\n", addr, version)

	if err := http.ListenAndServe(addr, mux); err != nil { //nolint:gosec
		fmt.Fprintf(os.Stderr, "fatal: %v\n", err)
		os.Exit(1)
	}
}
