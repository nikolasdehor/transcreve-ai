(() => {
  "use strict";

  const MEASUREMENT_ID = "G-0LVRWWE49G";
  const CONSENT_COOKIE = "ta_consent";
  const CONSENT_VERSION = "v1";
  const CONSENT_MAX_AGE = 15552000;
  const GRANTED = "granted";
  const DENIED = "denied";
  let analyticsLoaded = false;

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

  function closeBanner() {
    const banner = document.querySelector("[data-consent-banner]");
    if (banner) banner.remove();
  }

  function denyAnalytics() {
    const wasLoaded = analyticsLoaded;
    saveConsent(DENIED);
    window.gtag("consent", "update", {
      ad_storage: DENIED,
      ad_user_data: DENIED,
      ad_personalization: DENIED,
      analytics_storage: DENIED,
    });
    clearAnalyticsCookies();
    closeBanner();

    if (wasLoaded) window.location.reload();
  }

  function allowAnalytics() {
    saveConsent(GRANTED);
    loadAnalytics();
    closeBanner();
  }

  function showBanner() {
    closeBanner();

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
    banner.querySelector("[data-deny-analytics]").addEventListener("click", denyAnalytics);
    banner.querySelector("[data-allow-analytics]").addEventListener("click", allowAnalytics);
    banner.querySelector("[data-deny-analytics]").focus();
  }

  for (const button of document.querySelectorAll("[data-analytics-preferences]")) {
    button.addEventListener("click", showBanner);
  }

  const storedConsent = readConsent();
  if (storedConsent === GRANTED) {
    loadAnalytics();
  } else if (storedConsent !== DENIED) {
    showBanner();
  }
})();
