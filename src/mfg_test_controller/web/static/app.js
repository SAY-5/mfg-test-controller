"use strict";

(function () {
  const status = document.getElementById("live-status");
  const stepList = document.getElementById("live-steps");
  const summary = document.getElementById("live-summary");
  const buttons = document.querySelectorAll(".run-btn");

  if (!status || !stepList || !summary || buttons.length === 0) {
    return;
  }

  function resetView(planName) {
    stepList.innerHTML = "";
    summary.innerHTML = "";
    status.textContent = "starting " + planName + "...";
  }

  function startRun(button) {
    const planName = button.dataset.plan;
    const url = button.dataset.url;
    resetView(planName);
    buttons.forEach(function (b) { b.disabled = true; });

    fetch(url, { method: "POST" })
      .then(function (res) { return res.json(); })
      .then(function (data) {
        if (!data.stream_url) {
          status.textContent = "error: " + (data.error || "unknown");
          buttons.forEach(function (b) { b.disabled = false; });
          return;
        }
        status.textContent = "running " + planName + " (id " + data.run_id.slice(0, 8) + ")";
        consume(data.stream_url);
      })
      .catch(function (err) {
        status.textContent = "fetch error: " + err;
        buttons.forEach(function (b) { b.disabled = false; });
      });
  }

  function consume(streamUrl) {
    const es = new EventSource(streamUrl);

    es.addEventListener("step", function (ev) {
      const step = JSON.parse(ev.data);
      const li = document.createElement("li");
      li.className = step.passed ? "pass-row" : "fail-row";
      const measured = step.measured === null || step.measured === undefined
        ? ""
        : " measured=" + step.measured;
      li.textContent = step.name + " [" + step.device + "/" + step.action +
        " " + step.register + "] " + (step.passed ? "PASS" : "FAIL") +
        measured + " - " + step.detail;
      stepList.appendChild(li);
    });

    es.addEventListener("done", function (ev) {
      const done = JSON.parse(ev.data);
      const verdict = done.all_passed ? "PASS" : "FAIL";
      const klass = done.all_passed ? "pass" : "fail";
      summary.innerHTML = "<p>finished: <span class=\"" + klass + "\">" + verdict +
        "</span> &middot; " + done.passed + "/" + done.total +
        " passed in " + done.duration_s.toFixed(3) + " s &middot; " +
        "<a href=\"/runs/" + done.run_id + "\">view stored run</a></p>";
      status.textContent = "done";
      buttons.forEach(function (b) { b.disabled = false; });
      es.close();
    });

    es.addEventListener("error", function (ev) {
      if (ev.data) {
        try {
          const payload = JSON.parse(ev.data);
          summary.innerHTML = "<p class=\"fail\">error: " + payload.message + "</p>";
        } catch (_) {
          summary.innerHTML = "<p class=\"fail\">stream error</p>";
        }
      }
      buttons.forEach(function (b) { b.disabled = false; });
      es.close();
    });
  }

  buttons.forEach(function (btn) {
    btn.addEventListener("click", function () { startRun(btn); });
  });
})();
