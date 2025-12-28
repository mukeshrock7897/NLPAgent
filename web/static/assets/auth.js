const tabs = Array.from(document.querySelectorAll(".auth-tab"));
const panels = Array.from(document.querySelectorAll(".auth-panel"));
const noticeEl = document.getElementById("auth-notice");
const resetTab = document.getElementById("tab-reset");
const resetTokenInput = document.getElementById("reset-token");

function setNotice(message, type = "") {
  if (!noticeEl) return;
  noticeEl.textContent = message || "";
  noticeEl.className = "auth-notice" + (type ? ` ${type}` : "");
}

function showTab(id) {
  tabs.forEach((tab) => {
    tab.classList.toggle("active", tab.dataset.tab === id);
  });
  panels.forEach((panel) => {
    panel.classList.toggle("active", panel.id === `${id}-form`);
  });
  setNotice("");
}

async function checkExistingSession() {
  const res = await fetch("/api/auth/session");
  const data = await res.json();
  if (data.ok) {
    window.location.href = "/app";
  }
}

document.querySelectorAll("[data-tab]").forEach((btn) => {
  btn.addEventListener("click", () => showTab(btn.dataset.tab));
});

document.querySelectorAll("[data-tab-target]").forEach((btn) => {
  btn.addEventListener("click", () => showTab(btn.dataset.tabTarget));
});

const loginForm = document.getElementById("login-form");
if (loginForm) {
  loginForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    const form = new FormData(loginForm);
    const payload = {
      identifier: form.get("identifier")?.toString().trim() || "",
      password: form.get("password")?.toString() || "",
      remember: Boolean(form.get("remember")),
    };

    const res = await fetch("/api/auth/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const data = await res.json();
    if (!data.ok) {
      setNotice(data.error || "Login failed.", "is-error");
      return;
    }
    window.location.href = data.redirect || "/app";
  });
}

const signupForm = document.getElementById("signup-form");
if (signupForm) {
  signupForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    const form = new FormData(signupForm);
    const password = form.get("password")?.toString() || "";
    const confirm = form.get("confirm")?.toString() || "";
    if (password !== confirm) {
      setNotice("Passwords do not match.", "is-error");
      return;
    }
    const payload = {
      username: form.get("username")?.toString().trim() || "",
      email: form.get("email")?.toString().trim() || "",
      password,
      remember: Boolean(form.get("remember")),
    };

    const res = await fetch("/api/auth/signup", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const data = await res.json();
    if (!data.ok) {
      setNotice(data.error || "Signup failed.", "is-error");
      return;
    }
    window.location.href = data.redirect || "/app";
  });
}

const forgotForm = document.getElementById("forgot-form");
if (forgotForm) {
  forgotForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    const form = new FormData(forgotForm);
    const payload = {
      email: form.get("email")?.toString().trim() || "",
    };
    const res = await fetch("/api/auth/forgot", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const data = await res.json();
    if (!data.ok) {
      setNotice(data.error || "Unable to start reset.", "is-error");
      return;
    }
    if (data.reset_url) {
      setNotice("", "is-success");
      if (noticeEl) {
        noticeEl.innerHTML = `Reset link created. <a href=\"${data.reset_url}\">Open reset form</a>.`;
      }
      resetTab.hidden = false;
      const url = new URL(data.reset_url, window.location.origin);
      const token = url.searchParams.get("token");
      if (token && resetTokenInput) {
        resetTokenInput.value = token;
        showTab("reset");
      }
    } else {
      setNotice("If the email exists, a reset link is ready.", "is-success");
    }
  });
}

const resetForm = document.getElementById("reset-form");
if (resetForm) {
  resetForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    const form = new FormData(resetForm);
    const payload = {
      token: form.get("token")?.toString().trim() || "",
      password: form.get("password")?.toString() || "",
    };
    const res = await fetch("/api/auth/reset", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const data = await res.json();
    if (!data.ok) {
      setNotice(data.error || "Reset failed.", "is-error");
      return;
    }
    setNotice("Password updated. Please log in.", "is-success");
    showTab("login");
  });
}

(function boot() {
  checkExistingSession();
  const params = new URLSearchParams(window.location.search);
  const token = params.get("token");
  if (token && resetTokenInput) {
    resetTab.hidden = false;
    resetTokenInput.value = token;
    showTab("reset");
  }
})();
