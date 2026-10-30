// Renders the README images into docs/images/: the Mend banner, the zero-to-hero level map,
// screenshots of the web app (docs/mend.html) and previews of a PDF report.
// Needs Node with Playwright, plus pdftoppm (poppler) for the PDF previews.
// Usage: node webapp/readme_images.js        (run `make webapp reports` first)
const { chromium } = require("playwright");
const { execFileSync } = require("child_process");
const fs = require("fs");
const path = require("path");

const ROOT = path.resolve(__dirname, "..");
const OUT = path.join(ROOT, "docs", "images");
const APP = "file://" + path.join(ROOT, "docs", "mend.html");
const FONTS = `<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Unbounded:wght@600;700&family=Manrope:wght@400;600;700&family=JetBrains+Mono:wght@400&display=swap">`;
const BASE = `
  * { box-sizing: border-box; margin: 0 }
  body { width: 1600px; background: radial-gradient(900px 600px at 6% 10%, #0b3a37 0%, transparent 60%), #04110f;
         color: #e9f3f0; font-family: Manrope, sans-serif; overflow: hidden }
  .slab { position: absolute; width: 260px; height: 260px; border-radius: 30px;
          background: linear-gradient(145deg, var(--c1), var(--c2)); opacity: var(--o); filter: blur(var(--b));
          box-shadow: 0 30px 80px rgba(0,0,0,.45), inset 0 1px 0 rgba(255,255,255,.25);
          transform: translate(var(--x), var(--y)) rotate(-38deg) skewX(8deg) }
  .eyebrow { font: 600 15px Unbounded; letter-spacing: .18em; color: #3fc1b0; text-transform: uppercase }`;
const SLABS = [["#0e4a4a", "#0a2f33", .55, 6], ["#13605b", "#0c3b3d", .7, 3], ["#1b7a6f", "#0f4a49", .8, 1],
  ["#2b9a82", "#165c55", .88, 0], ["#5fbf6e", "#1f7a5d", .92, 0], ["#a6e05a", "#3d9a5a", .95, 0],
  ["#c6f24e", "#6cbf5a", .9, 1], ["#bfe9d8", "#6fb7b0", .75, 2], ["#8fd0dc", "#3d8fa3", .6, 5]];
const slabs = (x0, y0, dx, dy) => SLABS.map(([c1, c2, o, b], i) =>
  `<div class="slab" style="--x:${x0 + i * dx}px;--y:${y0 + i * dy}px;--c1:${c1};--c2:${c2};--o:${o};--b:${b}px"></div>`).join("");

const BANNER = `<!doctype html><html><head>${FONTS}<style>${BASE}
  body { height: 560px; position: relative }
  .copy { position: absolute; left: 96px; top: 110px; display: grid; gap: 22px; width: 780px }
  h1 { font: 700 150px/0.9 Unbounded; letter-spacing: .04em;
       background: linear-gradient(100deg, #f2fbf8 0%, #bff3e6 38%, #c6f24e 100%); -webkit-background-clip: text; color: transparent }
  h2 { font: 600 30px/1.25 Unbounded; letter-spacing: .05em; text-transform: uppercase }
  p { font-size: 21px; color: #b9cdc9; max-width: 640px; line-height: 1.5 }
</style></head><body>${slabs(860, -170, 70, 62)}
  <div class="copy"><span class="eyebrow">Agentic incident recovery</span><h1>MEND</h1>
  <h2>Agents that bring failing systems back</h2>
  <p>Break a live system on purpose. Let an agent diagnose and repair it. Trust only an independent verifier.</p></div>
</body></html>`;

const LEVELS = [
  ["0", "Look", "Open the Mend web app. Nothing to install."],
  ["1", "Explore", "Replay incidents, compare agents, read the verdicts."],
  ["2", "Report", "Download PDF and CSV incident reports."],
  ["3", "Run it", "Start the real system with Docker. Break it and fix it."],
  ["4", "Benchmark", "Score agents on all 22 incidents. Rebuild reports and the app."],
  ["5", "Extend", "Add your own agent, fault or scenario. Run Mend AI."],
];
const LEVELMAP = `<!doctype html><html><head>${FONTS}<style>${BASE}
  body { height: 430px; padding: 56px 64px; position: relative }
  .head { display: flex; align-items: baseline; gap: 22px; margin-bottom: 34px }
  .head b { font: 700 34px Unbounded; letter-spacing: .04em; text-transform: uppercase }
  .row { display: grid; grid-template-columns: repeat(6, 1fr); gap: 14px; position: relative }
  .row::before { content: ""; position: absolute; left: 6%; right: 6%; top: 34px; height: 3px;
                 background: linear-gradient(90deg, #13605b, #3fc1b0, #c6f24e) }
  .lv { position: relative; display: grid; gap: 12px; justify-items: start }
  .n { width: 70px; height: 70px; border-radius: 50%; display: grid; place-items: center; font: 700 26px Unbounded;
       background: #0c2321; border: 2px solid #3fc1b0; color: #e9f3f0 }
  .lv:last-child .n { background: #c6f24e; color: #0b1a06; border-color: #c6f24e; box-shadow: 0 0 30px rgba(198,242,78,.4) }
  .t { font: 700 20px Unbounded; text-transform: uppercase; letter-spacing: .05em }
  .d { font-size: 16.5px; color: #a7bdb9; line-height: 1.45 }
</style></head><body>
  <div class="head"><b>Zero to hero</b><span class="eyebrow">six levels, start anywhere</span></div>
  <div class="row">${LEVELS.map(([n, t, d]) => `<div class="lv"><div class="n">${n}</div><div class="t">${t}</div><div class="d">${d}</div></div>`).join("")}</div>
</body></html>`;

(async () => {
  fs.mkdirSync(OUT, { recursive: true });
  const browser = await chromium.launch();
  const shot = async (html, file, height) => {
    const p = await browser.newPage({ viewport: { width: 1600, height }, deviceScaleFactor: 1 });
    await p.setContent(html, { waitUntil: "networkidle" });
    await p.screenshot({ path: path.join(OUT, file) });
    await p.close();
  };
  await shot(BANNER, "banner.png", 560);
  await shot(LEVELMAP, "levels.png", 430);

  const app = async (hash, viewport, run) => {
    const p = await browser.newPage({ viewport, deviceScaleFactor: 1 });
    await p.goto(APP + hash, { waitUntil: "networkidle" });
    await p.addStyleTag({ content: ".slab { animation: none !important } .nav { position: static !important }" });
    await p.waitForTimeout(400);
    await run(p);
    await p.close();
  };
  const jpg = (name) => ({ path: path.join(OUT, name), type: "jpeg", quality: 84 });
  await app("", { width: 1440, height: 860 }, (p) => p.screenshot(jpg("app-hero.jpg")));
  await app("", { width: 1440, height: 900 }, async (p) => {
    const box = await (await p.$("#results")).boundingBox();
    const end = await (await p.$("#reports")).boundingBox();
    await p.screenshot({ ...jpg("app-results.jpg"), fullPage: true,
      clip: { x: 0, y: box.y - 24, width: 1440, height: end.y + end.height - box.y + 48 } });
  });
  await app("#ho-11-conn-leak-and-dns", { width: 1440, height: 900 }, async (p) => {
    await p.click('[data-agent="reasoner"]');
    await p.evaluate(() => scrollTo(0, 0));   // the click scrolls; clip boxes must be measured from the top
    const box = await (await p.$("#replay")).boundingBox();
    await p.screenshot({ ...jpg("app-replay.jpg"), fullPage: true, clip: { x: 0, y: box.y - 24, width: 1440, height: 1250 } });
  });
  await app("#ho-05-db-lock", { width: 1440, height: 900 }, async (p) => {
    await p.click('[data-agent="rules"]');
    await p.evaluate(() => scrollTo(0, 0));   // the click scrolls; clip boxes must be measured from the top
    const v = await p.$eval(".verdict", e => { const r = e.closest(".card").getBoundingClientRect(); return { y: r.y }; });
    const a = await (await p.$(".advice")).boundingBox();
    await p.screenshot({ ...jpg("app-verdict.jpg"), fullPage: true,
      clip: { x: a.x - 16, y: v.y - 16, width: a.width + 32, height: a.y + a.height - v.y + 32 } });
  });
  await browser.close();

  const pdf = path.join(ROOT, "docs", "reports", "baseline-rules.pdf");
  const pages = Number(/Pages:\s+(\d+)/.exec(execFileSync("pdfinfo", [pdf]).toString())[1]);
  const incident = [...Array(pages).keys()].map(i => i + 1).find(i =>
    /ho-05-db-lock[\s\S]*PAGER ALERT/i.test(execFileSync("pdftotext", ["-f", String(i), "-l", String(i), pdf, "-"]).toString()));
  for (const [page, name] of [[1, "pdf-cover"], [2, "pdf-overview"], [incident, "pdf-incident"]]) {
    execFileSync("pdftoppm", ["-r", "70", "-jpeg", "-jpegopt", "quality=84", "-singlefile", "-f", String(page),
      "-l", String(page), pdf, path.join(OUT, name)]);
  }
  for (const f of fs.readdirSync(OUT)) console.log(`docs/images/${f}  ${Math.round(fs.statSync(path.join(OUT, f)).size / 1024)} KB`);
})();
