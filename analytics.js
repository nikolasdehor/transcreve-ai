(() => {
  "use strict";

  const MEASUREMENT_ID = "G-0LVRWWE49G";
  const CONSENT_COOKIE = "ta_consent";
  const CONSENT_VERSION = "v1";
  const CONSENT_MAX_AGE = 15552000;
  const CONSENT_CHANNEL = "transcreveai_consent";
  const FOCUS_RETURN_KEY = "transcreveai_consent_return_focus";
  const GRANTED = "granted";
  const DENIED = "denied";
  let analyticsLoaded = false;
  let consentReturnFocus = null;
  const consentChannel = "BroadcastChannel" in window
    ? new BroadcastChannel(CONSENT_CHANNEL)
    : null;

  window.dataLayer = window.dataLayer || [];
  window.gtag = function gtag() {
    window.dataLayer.push(arguments);
  };

  window.gtag("consent", "default", {
    ad_storage: DENIED,
    ad_user_data: DENIED,
    ad_personalization: DENIED,
    analytics_storage: DENIED,
    functionality_storage: GRANTED,
    personalization_storage: DENIED,
    security_storage: GRANTED,
    wait_for_update: 500,
  });
  window.gtag("set", "ads_data_redaction", true);
  window.gtag("set", "url_passthrough", false);

  function loadAnalytics() {
    if (analyticsLoaded) return;
    analyticsLoaded = true;

    window.gtag("consent", "update", {
      analytics_storage: GRANTED,
    });
    window.gtag("js", new Date());
    window.gtag("config", MEASUREMENT_ID, {
      allow_google_signals: false,
      allow_ad_personalization_signals: false,
      cookie_domain: "none",
      cookie_expires: CONSENT_MAX_AGE,
      cookie_update: false,
      page_location: stripQueryAndFragment(window.location.href),
      page_referrer: stripQueryAndFragment(document.referrer),
    });

    const script = document.createElement("script");
    script.async = true;
    script.src = `https://www.googletagmanager.com/gtag/js?id=${encodeURIComponent(MEASUREMENT_ID)}`;
    document.head.append(script);
  }

  function stripQueryAndFragment(value) {
    if (!value) return "";

    try {
      const url = new URL(value, window.location.href);
      return `${url.origin}${url.pathname}`;
    } catch {
      return "";
    }
  }

  function clearAnalyticsCookies() {
    const names = document.cookie
      .split(";")
      .map((cookie) => cookie.trim().split("=")[0])
      .filter((name) => name.startsWith("_ga"));

    for (const name of names) {
      document.cookie = `${name}=; Max-Age=0; path=/; SameSite=Lax`;
    }
  }

  function saveConsent(value) {
    const secure = window.location.protocol === "https:" ? "; Secure" : "";
    document.cookie = `${CONSENT_COOKIE}=${CONSENT_VERSION}:${value}; Max-Age=${CONSENT_MAX_AGE}; Path=/; SameSite=Lax${secure}`;
  }

  function readConsent() {
    const prefix = `${CONSENT_COOKIE}=${CONSENT_VERSION}:`;
    const consentCookie = document.cookie
      .split(";")
      .map((cookie) => cookie.trim())
      .find((cookie) => cookie.startsWith(prefix));
    return consentCookie ? consentCookie.slice(prefix.length) : null;
  }

  function closeBanner(restoreFocus = false) {
    const banner = document.querySelector("[data-consent-banner]");
    if (banner) banner.remove();
    if (restoreFocus && consentReturnFocus?.isConnected) {
      consentReturnFocus.focus();
    }
    consentReturnFocus = null;
  }

  function denyAnalytics(shouldBroadcast = true) {
    const wasLoaded = analyticsLoaded;
    const shouldRestoreAfterReload = Boolean(consentReturnFocus?.isConnected);
    saveConsent(DENIED);
    window.gtag("consent", "update", {
      ad_storage: DENIED,
      ad_user_data: DENIED,
      ad_personalization: DENIED,
      analytics_storage: DENIED,
    });
    clearAnalyticsCookies();
    closeBanner(true);
    if (shouldBroadcast) consentChannel?.postMessage(DENIED);

    if (wasLoaded) {
      if (shouldRestoreAfterReload) {
        try {
          window.sessionStorage.setItem(FOCUS_RETURN_KEY, "true");
        } catch {
          // Focus restoration is best effort when storage is unavailable.
        }
      }
      window.location.reload();
    }
  }

  function allowAnalytics() {
    saveConsent(GRANTED);
    loadAnalytics();
    closeBanner(true);
  }

  function showBanner(returnFocus = null) {
    closeBanner();
    consentReturnFocus = returnFocus;

    const banner = document.createElement("section");
    banner.className = "consent-banner";
    banner.dataset.consentBanner = "";
    banner.setAttribute("role", "dialog");
    banner.setAttribute("aria-labelledby", "analytics-consent-title");
    banner.setAttribute("aria-describedby", "analytics-consent-description");
    banner.innerHTML = `
      <div>
        <h2 id="analytics-consent-title">Optional analytics</h2>
        <p id="analytics-consent-description">
          Help us understand site traffic with Google Analytics. It only loads
          if you allow it. <a href="privacy.html#website-analytics">Learn about website analytics</a>.
        </p>
      </div>
      <div class="consent-actions">
        <button type="button" class="button" data-deny-analytics>Reject analytics</button>
        <button type="button" class="button" data-allow-analytics>Allow analytics</button>
      </div>
    `;
    document.body.append(banner);
    banner.querySelector("[data-deny-analytics]").addEventListener("click", () => denyAnalytics());
    banner.querySelector("[data-allow-analytics]").addEventListener("click", allowAnalytics);
    banner.querySelector("[data-deny-analytics]").focus();
  }

  for (const button of document.querySelectorAll("[data-analytics-preferences]")) {
    button.addEventListener("click", () => showBanner(button));
  }

  if (consentChannel) {
    consentChannel.addEventListener("message", (event) => {
      if (event.data === DENIED) denyAnalytics(false);
    });
  }

  document.addEventListener("visibilitychange", () => {
    if (!document.hidden && analyticsLoaded && readConsent() !== GRANTED) {
      denyAnalytics(false);
    }
  });

  const storedConsent = readConsent();
  if (storedConsent === GRANTED) {
    loadAnalytics();
  } else if (storedConsent !== DENIED) {
    showBanner();
  }

  try {
    if (window.sessionStorage.getItem(FOCUS_RETURN_KEY) === "true") {
      window.sessionStorage.removeItem(FOCUS_RETURN_KEY);
      document.querySelector("[data-analytics-preferences]")?.focus();
    }
  } catch {
    // Focus restoration is best effort when storage is unavailable.
  }
})();
