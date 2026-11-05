(() => {
  const agentId = __AGENT_ID__;
  const entryId = __ENTRY_ID__;
  const allowedOrigins = new Set(__ALLOWED_ORIGINS__);
  const scriptUrl = document.currentScript?.src;
  if (!scriptUrl || !allowedOrigins.has(window.location.origin)) return;

  const marker = `${agentId}/${entryId}`;
  if ([...document.querySelectorAll("iframe[data-loomrise-widget]")]
    .some(frame => frame.dataset.loomriseWidget === marker)) return;

  const widgetUrl = new URL(
    `/widget/${encodeURIComponent(agentId)}/${encodeURIComponent(entryId)}`,
    scriptUrl,
  );
  const mount = () => {
    if (!document.body) return;
    const frame = document.createElement("iframe");
    frame.title = "Loomrise 客服窗口";
    frame.loading = "lazy";
    frame.dataset.loomriseWidget = marker;
    frame.src = widgetUrl.href;
    frame.style.cssText = [
      "position:fixed", "right:16px", "bottom:16px", "z-index:2147483000",
      "width:min(420px,calc(100vw - 32px))", "height:min(720px,calc(100vh - 32px))",
      "border:1px solid #d7e0dc", "border-radius:8px", "background:#fff",
    ].join(";");
    document.body.append(frame);
  };

  if (document.body) mount();
  else document.addEventListener("DOMContentLoaded", mount, { once: true });
})();
