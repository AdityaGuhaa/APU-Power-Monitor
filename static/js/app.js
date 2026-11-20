/* =====================================================================
   APU-Power-Monitor - Frontend
   Copyright (c) 2026 Aditya Guha
   Licensed under the MIT License. See LICENSE in the project root.

   Socket.IO client + Chart.js rendering. Every metric is nullable: `null`
   means the active provider cannot read that sensor, which is rendered as an
   explicit "unavailable" state rather than as a zero.
   ===================================================================== */

(function () {
    "use strict";

    // -----------------------------------------------------------------------
    // Config (bootstrapped from the template, refined by the apu_meta event)
    // -----------------------------------------------------------------------
    const body = document.body;
    const state = {
        intervalMs: Number(body.dataset.intervalMs) || 500,
        historySeconds: Number(body.dataset.historySeconds) || 60,
        selectedDevice: 0,
        deviceNames: [],
        powerLimit: null,
        powerMaxLimit: null,
        powerPeak: null,
        powerAxisMax: null,
        memoryAxisMax: null,
    };

    const COLORS = {
        power: "#3ddc84",
        powerFillTop: "rgba(61, 220, 132, 0.18)",
        powerFillBottom: "rgba(61, 220, 132, 0.02)",
        memory: "#4fc3f7",
        memoryFillTop: "rgba(79, 195, 247, 0.18)",
        memoryFillBottom: "rgba(79, 195, 247, 0.02)",
        limit: "rgba(255, 180, 50, 0.45)",
        grid: "rgba(255, 255, 255, 0.04)",
        tick: "rgba(255, 255, 255, 0.25)",
    };

    let powerChart = null;
    let memoryChart = null;

    // -----------------------------------------------------------------------
    // Helpers
    // -----------------------------------------------------------------------
    function historyPoints() {
        return Math.max(2, Math.round((state.historySeconds * 1000) / state.intervalMs));
    }

    /**
     * X-axis labels in real seconds. The label step follows the sampling
     * interval, so a 500 ms cadence over 120 points reads as 60 s, not 120 s.
     */
    function buildLabels() {
        const count = historyPoints();
        const step = state.intervalMs / 1000;
        const labels = [];
        for (let i = count - 1; i >= 0; i--) {
            const secondsAgo = i * step;
            labels.push(secondsAgo === 0 ? "0s" : "-" + Math.round(secondsAgo) + "s");
        }
        return labels;
    }

    /** Round an axis maximum up to a human-friendly value. */
    function niceCeil(value) {
        if (!(value > 0)) return 1;
        const magnitude = Math.pow(10, Math.floor(Math.log10(value)));
        const normalized = value / magnitude;
        const step = [1, 1.25, 1.5, 2, 2.5, 3, 4, 5, 6, 8, 10].find(function (candidate) {
            return normalized <= candidate;
        });
        return step * magnitude;
    }

    function text(id, value) {
        const node = document.getElementById(id);
        if (node) node.textContent = value;
    }

    const DASH = "—";

    function format(value, digits, suffix) {
        if (value === null || value === undefined || Number.isNaN(value)) return DASH;
        return value.toFixed(digits) + (suffix || "");
    }

    function mibToGb(value) {
        return value === null || value === undefined ? null : value / 1024;
    }

    function percentOf(part, whole) {
        if (part === null || whole === null || !(whole > 0)) return null;
        return (part / whole) * 100;
    }

    // -----------------------------------------------------------------------
    // Charts
    // -----------------------------------------------------------------------
    function buildChart(canvasId, accent, fillTop, fillBottom, label, initialMax) {
        const canvas = document.getElementById(canvasId);
        const ctx = canvas.getContext("2d");
        const height = (canvas.parentElement && canvas.parentElement.offsetHeight) || 240;
        const gradient = ctx.createLinearGradient(0, 0, 0, height);
        gradient.addColorStop(0, fillTop);
        gradient.addColorStop(1, fillBottom);

        return new Chart(ctx, {
            type: "line",
            data: {
                labels: buildLabels(),
                datasets: [
                    {
                        label: label,
                        data: new Array(historyPoints()).fill(null),
                        borderColor: accent,
                        backgroundColor: gradient,
                        borderWidth: 1.5,
                        fill: true,
                        tension: 0.3,
                        pointRadius: 0,
                        pointHoverRadius: 3,
                        pointHoverBackgroundColor: accent,
                        spanGaps: false,
                    },
                    {
                        label: "Limit",
                        data: new Array(historyPoints()).fill(null),
                        borderColor: COLORS.limit,
                        borderWidth: 1,
                        borderDash: [4, 3],
                        fill: false,
                        tension: 0,
                        pointRadius: 0,
                        pointHoverRadius: 0,
                    },
                ],
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                animation: false,
                interaction: { mode: "index", intersect: false },
                layout: { padding: { top: 4, right: 4, bottom: 0, left: 0 } },
                plugins: {
                    legend: { display: false },
                    tooltip: {
                        backgroundColor: "rgba(0, 0, 0, 0.85)",
                        titleColor: "#ccc",
                        bodyColor: "#eee",
                        borderColor: "#222",
                        borderWidth: 1,
                        cornerRadius: 4,
                        padding: 8,
                        titleFont: { size: 10, family: "Inter" },
                        bodyFont: { size: 11, family: "Inter" },
                        displayColors: false,
                    },
                },
                scales: {
                    x: {
                        grid: { color: COLORS.grid, lineWidth: 0.5 },
                        ticks: {
                            color: COLORS.tick,
                            font: { size: 9, family: "Inter" },
                            maxTicksLimit: 7,
                            padding: 4,
                            autoSkip: true,
                        },
                        border: { display: false },
                    },
                    y: {
                        min: 0,
                        max: initialMax,
                        grid: { color: COLORS.grid, lineWidth: 0.5 },
                        ticks: {
                            color: COLORS.tick,
                            font: { size: 9, family: "Inter" },
                            maxTicksLimit: 5,
                            padding: 6,
                        },
                        border: { display: false },
                    },
                },
            },
        });
    }

    function initCharts() {
        powerChart = buildChart(
            "powerChart", COLORS.power, COLORS.powerFillTop, COLORS.powerFillBottom, "Power (W)", 15
        );
        memoryChart = buildChart(
            "memoryChart", COLORS.memory, COLORS.memoryFillTop, COLORS.memoryFillBottom, "Memory (GB)", 2
        );
    }

    function relabelCharts() {
        [powerChart, memoryChart].forEach(function (chart) {
            if (!chart) return;
            chart.data.labels = buildLabels();
            chart.data.datasets.forEach(function (dataset) {
                dataset.data = new Array(historyPoints()).fill(null);
            });
            chart.update("none");
        });
    }

    function pushPoint(chart, value, limitValue) {
        if (!chart) return;
        const count = historyPoints();
        const series = chart.data.datasets[0].data;
        const limits = chart.data.datasets[1].data;

        // Pad on the left so the window is always exactly as long as the axis:
        // the newest sample sits at 0s on the right and scrolls leftwards.
        while (series.length < count) series.unshift(null);
        while (limits.length < count) limits.unshift(null);

        series.push(value === null || value === undefined ? null : value);
        limits.push(limitValue === null || limitValue === undefined ? null : limitValue);

        while (series.length > count) series.shift();
        while (limits.length > count) limits.shift();

        chart.update("none");
    }

    /**
     * Keep the Y axis stable: lock it to the known hardware ceiling when there
     * is one, otherwise grow it to fit the highest value seen so far. It never
     * shrinks, so the trace does not jump around between frames.
     */
    function growAxis(chart, key, value) {
        if (!chart || value === null || value === undefined) return;
        const current = state[key];
        if (current !== null && value <= current * 0.85) return;
        const next = niceCeil(Math.max(value * 1.15, current || 0));
        if (current !== null && next <= current) return;
        state[key] = next;
        chart.options.scales.y.max = next;
    }

    function lockAxis(chart, key, ceiling) {
        if (!chart || ceiling === null || ceiling === undefined || !(ceiling > 0)) return false;
        const target = ceiling;
        if (state[key] === target) return true;
        state[key] = target;
        chart.options.scales.y.max = target;
        return true;
    }

    // -----------------------------------------------------------------------
    // DOM
    // -----------------------------------------------------------------------
    function setConnection(connected, message) {
        const dot = document.getElementById("connection-dot");
        dot.className = "connection-dot " + (connected ? "connected" : "disconnected");
        text("connection-status", message || (connected ? "Live" : "Disconnected"));
    }

    function setPanelAvailability(panelId, available) {
        const panel = document.getElementById(panelId);
        if (panel) panel.classList.toggle("unavailable", !available);
    }

    function renderNotes(notes) {
        const container = document.getElementById("notes");
        if (!container) return;
        const unique = [];
        (notes || []).forEach(function (note) {
            if (note && unique.indexOf(note) === -1) unique.push(note);
        });
        if (unique.join("|") === container.dataset.rendered) return;
        container.dataset.rendered = unique.join("|");
        container.innerHTML = "";
        unique.forEach(function (note) {
            const span = document.createElement("span");
            span.className = "note";
            span.textContent = note;
            container.appendChild(span);
        });
    }

    function syncDeviceSelector(devices) {
        const names = devices.map(function (device) {
            return device.device_name || "Unknown device";
        });
        const bar = document.getElementById("device-bar");
        const select = document.getElementById("device-select");

        bar.classList.toggle("visible", names.length > 1);
        if (names.join("|") === state.deviceNames.join("|")) return;

        state.deviceNames = names;
        select.innerHTML = "";
        names.forEach(function (name, index) {
            const option = document.createElement("option");
            option.value = String(index);
            option.textContent = name;
            select.appendChild(option);
        });
        if (state.selectedDevice >= names.length) state.selectedDevice = 0;
        select.value = String(state.selectedDevice);
    }

    function render(device) {
        const memoryUsedGb = mibToGb(device.memory_used);
        const memoryTotalGb = mibToGb(device.memory_total);
        const power = device.power_draw;
        const powerLimit = device.power_limit;

        if (power !== null && (state.powerPeak === null || power > state.powerPeak)) {
            state.powerPeak = power;
        }

        // Summary strip
        text("device-name", device.device_name || DASH);
        text("temperature", format(device.temperature, 0, " °C"));
        text("gpu-util", format(device.gpu_utilization, 0, " %"));
        text("cpu-util", format(device.cpu_utilization, 0, " %"));
        text("power-current", format(power, 1, " W"));
        text("power-limit", powerLimit === null ? "" : " / " + format(powerLimit, 0, " W"));
        text("memory-used", format(memoryUsedGb, 1, " GB"));
        text("memory-total", memoryTotalGb === null ? "" : " / " + format(memoryTotalGb, 1, " GB"));

        // Panel readings
        text("reading-power", format(power, 1));
        text("reading-memory", format(memoryUsedGb, 1));

        // Power footer
        text("stat-power", format(power, 1));
        text("stat-power-peak", format(state.powerPeak, 1));
        text("stat-power-limit", format(powerLimit, 0));
        text("stat-power-pct", format(percentOf(power, powerLimit), 0));

        // Memory footer
        text("stat-memory-used", format(memoryUsedGb, 1));
        text("stat-memory-total", format(memoryTotalGb, 1));
        text("stat-memory-pct", format(percentOf(device.memory_used, device.memory_total), 0));

        setPanelAvailability("panel-power", power !== null);
        setPanelAvailability("panel-memory", device.memory_used !== null);

        // Axes: lock to the hardware/configured ceiling, else grow to fit.
        if (!lockAxis(powerChart, "powerAxisMax", device.power_max_limit || powerLimit)) {
            growAxis(powerChart, "powerAxisMax", power);
        }
        if (!lockAxis(memoryChart, "memoryAxisMax", memoryTotalGb)) {
            growAxis(memoryChart, "memoryAxisMax", memoryUsedGb);
        }

        pushPoint(powerChart, power, powerLimit);
        pushPoint(memoryChart, memoryUsedGb, memoryTotalGb);

        renderNotes(device.notes);
    }

    function applyMeta(meta) {
        if (!meta) return;
        let relabel = false;
        if (meta.interval_ms && meta.interval_ms !== state.intervalMs) {
            state.intervalMs = meta.interval_ms;
            relabel = true;
        }
        if (meta.history_seconds && meta.history_seconds !== state.historySeconds) {
            state.historySeconds = meta.history_seconds;
            relabel = true;
        }
        if (relabel) relabelCharts();

        state.powerLimit = meta.power_limit ?? null;
        state.powerMaxLimit = meta.power_max_limit ?? null;

        if (meta.provider) {
            text("provider-chip", meta.provider);
            text("footer-provider", "provider: " + meta.provider);
            const chip = document.getElementById("provider-chip");
            if (chip && meta.provider_description) chip.title = meta.provider_description;
        }
        text("footer-interval", state.intervalMs + " ms refresh");
        text("footer-history", state.historySeconds + " second history");
    }

    // -----------------------------------------------------------------------
    // Socket
    // -----------------------------------------------------------------------
    function initSocket() {
        const socket = io();

        socket.on("connect", function () {
            setConnection(true, "Live");
        });

        socket.on("disconnect", function () {
            setConnection(false, "Disconnected");
        });

        socket.on("connect_error", function () {
            setConnection(false, "Connection failed");
        });

        socket.on("apu_meta", applyMeta);

        socket.on("apu_data", function (payload) {
            if (!payload || !payload.devices || payload.devices.length === 0) return;
            setConnection(true, "Live");
            syncDeviceSelector(payload.devices);
            const index = Math.min(state.selectedDevice, payload.devices.length - 1);
            render(payload.devices[index]);
        });

        socket.on("apu_error", function (payload) {
            setConnection(false, "No sensor data");
            console.warn("[APU-Power-Monitor]", payload && payload.message);
        });

        document.getElementById("device-select").addEventListener("change", function (event) {
            state.selectedDevice = Number(event.target.value) || 0;
            state.powerPeak = null;
            state.powerAxisMax = null;
            state.memoryAxisMax = null;
            relabelCharts();
        });
    }

    // -----------------------------------------------------------------------
    document.addEventListener("DOMContentLoaded", function () {
        initCharts();
        initSocket();
    });
})();
