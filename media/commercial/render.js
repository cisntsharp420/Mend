// Mend commercial: motion graphics rendered frame by frame (deterministic), timed to the voice-over.
// Usage: node render.js <timings.json> <out.mp4> [audio.wav] [--no-captions] [--stills]
// timings.json: [{id, start, end, line}] (written by make_commercial.py). Needs Playwright and ffmpeg.
const { chromium } = require("playwright");
const { spawn } = require("child_process");
const fs = require("fs");
const path = require("path");

const [, , TIMINGS, OUT, AUDIO_ARG] = process.argv;
const AUDIO = AUDIO_ARG && !AUDIO_ARG.startsWith("--") ? AUDIO_ARG : null;
const CAPTIONS = !process.argv.includes("--no-captions");
const STILLS = process.argv.includes("--stills");
const FONTS = path.resolve(__dirname, "../../recovery/assets/fonts");
const ff = (n, f) => `@font-face{font-family:${n};src:url(data:font/ttf;base64,${fs.readFileSync(path.join(FONTS, f)).toString("base64")})}`;
const FPS = 30, W = 1920, H = 1080;
const T = JSON.parse(fs.readFileSync(TIMINGS, "utf8"));
const DUR = T[T.length - 1].end;

const SL = [["#0e4a4a","#0a2f33",.55],["#13605b","#0c3b3d",.7],["#1b7a6f","#0f4a49",.8],["#2b9a82","#165c55",.88],["#5fbf6e","#1f7a5d",.92],
            ["#a6e05a","#3d9a5a",.95],["#c6f24e","#6cbf5a",.9],["#bfe9d8","#6fb7b0",.75],["#8fd0dc","#3d8fa3",.6]];
const words = (s, cls = "") => s.split(" ").map((w) => `<span class="w ${cls}">${w}</span>`).join(" ");

// Shop diagram: node centres and the edges traffic flows along
const N = { cust: [120, 90], web: [380, 90], api: [640, 90], db: [640, 330], cache: [880, 330], worker: [380, 330] };
const E = [["cust", "web"], ["web", "api"], ["api", "db"], ["api", "cache"], ["worker", "db"]];
const node = (k, label) => `<g class="node" data-k="${k}"><rect x="${N[k][0] - 100}" y="${N[k][1] - 38}" width="200" height="76" rx="18"/>
  <text x="${N[k][0]}" y="${N[k][1] + 9}">${label}</text></g>`;
const diagram = `<svg id="shop" viewBox="0 0 1000 430" width="1000" height="430">
  ${E.map(([a, b], i) => `<path class="edge" id="e${i}" d="M${N[a][0]} ${N[a][1]} L${N[b][0]} ${N[b][1]}"/>`).join("")}
  ${E.map((_, i) => [0, 1, 2].map((j) => `<circle class="dot" data-e="${i}" data-j="${j}" r="9"/>`).join("")).join("")}
  <circle id="ring" cx="${N.db[0]}" cy="${N.db[1]}" r="60"/>
  ${node("cust", "Customers")}${node("web", "Website")}${node("api", "Shop API")}${node("db", "Database")}${node("cache", "Cache")}${node("worker", "Worker")}</svg>`;

const HTML = `<!doctype html><html><head><style>${ff("D","Unbounded-Bold.ttf")}${ff("B","Manrope-Regular.ttf")}${ff("BB","Manrope-Bold.ttf")}${ff("M","JetBrainsMono-Regular.ttf")}
*{margin:0;box-sizing:border-box}
body{width:${W}px;height:${H}px;overflow:hidden;background:#04110f;color:#e9f3f0;font-family:B;position:relative}
#glow{position:absolute;inset:0;background:radial-gradient(1300px 900px at 8% 12%,#0b3a37 0%,transparent 62%)}
.slab{position:absolute;width:560px;height:560px;border-radius:64px;background:linear-gradient(145deg,var(--a),var(--b));box-shadow:0 40px 110px rgba(0,0,0,.5),inset 0 1px 0 rgba(255,255,255,.25)}
.sc{position:absolute;inset:0;opacity:0}
.w{display:inline-block;opacity:0}
.lime{color:#c6f24e}.bad{color:#ff8a78}
.h{position:absolute;left:150px;font:700 96px/1.05 D;letter-spacing:.02em;text-transform:uppercase}
.m{position:absolute;left:150px;font:700 62px/1.1 D;letter-spacing:.02em;text-transform:uppercase}
.mark{position:absolute;left:150px;top:70px;font:700 34px D;letter-spacing:.18em}
#ecg{position:absolute;left:0;top:640px}
#ecg path{fill:none;stroke-width:6;stroke-linecap:round;stroke-linejoin:round}
#shop{position:absolute;left:1000px;top:300px;transform:scale(.8);transform-origin:0 0}
.edge{stroke:#2a4b47;stroke-width:5}
.dot{fill:#c6f24e}
.node rect{fill:#112e2b;stroke:#3fc1b0;stroke-width:3}.node text{font:30px BB;fill:#e9f3f0;text-anchor:middle}
.node.down rect{fill:#3a1714;stroke:#ff8a78}.node.down text{fill:#ff8a78}
#ring{fill:none;stroke:#ff8a78;stroke-width:5;opacity:0}
.panel{position:absolute;background:#0c2321;border:2px solid #1f3d3a;border-radius:28px;padding:34px 40px}
.log{font:28px/1.65 M;color:#9db5b0;white-space:nowrap}
.hyp{display:grid;grid-template-columns:560px 1fr 120px;gap:24px;align-items:center;font:30px BB;margin-top:26px}
.track{height:34px;background:#081a18;border-radius:17px;overflow:hidden}.fill{height:100%;width:0;border-radius:17px;background:#4d6964}
.fill.top{background:linear-gradient(90deg,#3fc1b0,#c6f24e)}
.pct{font:700 36px D;text-align:right}
.chip{display:flex;gap:26px;align-items:center;font:36px BB;opacity:0;margin-top:24px}
.chip b{font:700 26px D;letter-spacing:.1em;color:#04110f;background:#c6f24e;border-radius:12px;padding:10px 18px;font-weight:normal}
#check{position:absolute;left:1260px;top:300px}
#check circle{fill:none;stroke:#c6f24e;stroke-width:14}#check path{fill:none;stroke:#c6f24e;stroke-width:22;stroke-linecap:round;stroke-linejoin:round}
.stamp{position:absolute;left:1120px;top:760px;white-space:nowrap;transform-origin:50% 50%;font:700 34px D;letter-spacing:.14em;color:#c6f24e;border:5px solid #c6f24e;border-radius:18px;padding:16px 30px;opacity:0}
.big{position:absolute;left:150px;top:260px;font:700 240px/1 D;color:#c6f24e;letter-spacing:-.01em}
.bars{position:absolute;left:1090px;top:300px;width:690px;display:grid;gap:30px}
.bar{display:grid;grid-template-columns:230px 1fr 100px;gap:22px;align-items:center;font:30px BB}
.bar .pct{font-size:32px}
#wipe{position:absolute;top:-400px;width:900px;height:${H + 800}px;transform:skewX(-18deg);background:linear-gradient(90deg,#13605b,#3fc1b0 40%,#c6f24e);display:none}
#cap{position:absolute;left:50%;bottom:64px;transform:translateX(-50%);max-width:1500px;text-align:center;font:34px/1.35 BB;color:#fff;
     background:rgba(4,17,15,.72);border:1px solid rgba(170,235,220,.18);border-radius:16px;padding:16px 30px;opacity:0}
#prog{position:absolute;left:0;bottom:0;height:6px;background:linear-gradient(90deg,#3fc1b0,#c6f24e)}
</style></head><body><div id="glow"></div>
<div id="slabs">${SL.map(([a, b, o], i) => `<div class="slab" data-i="${i}" style="--a:${a};--b:${b};opacity:${o}"></div>`).join("")}</div>
<div class="mark" id="mark">MEND</div>

<div class="sc" id="hook">
  <svg id="ecg" width="${W}" height="260" viewBox="0 0 ${W} 260"><path id="ecgline" d=""/></svg>
  <div class="h" style="top:300px">${words("When systems fail,")}<br>${words("every minute counts.", "lime")}</div></div>

<div class="sc" id="problem">${diagram}
  <div class="m" style="top:300px;font-size:58px">${words("Orders stop.")}<br>${words("Customers", "bad")}<br>${words("can't pay.", "bad")}</div>
  <div class="m" style="top:590px;font-size:34px;color:#c9dad6;max-width:760px">${words("Someone has to find out why, fast.")}</div></div>

<div class="sc" id="meet">
  <div class="m" style="top:150px">${words("Meet")} ${words("Mend AI.", "lime")}</div>
  <div class="panel" style="left:150px;top:300px;width:1620px;height:250px;overflow:hidden"><div class="log" id="log">
    <div><span class="bad">ERROR</span> api   probe /api/orders: 503 database error</div>
    <div><span class="bad">FATAL</span> postgres  remaining connection slots are reserved</div>
    <div>metric  postgres connections 38 / 40</div>
    <div><span class="bad">ERROR</span> api   Name does not resolve</div>
    <div>change  api v2 deployed 0.4 min ago: point api at new primary database endpoint</div>
    <div>diag    application report-backfill holds 37 sessions</div></div></div>
  <div class="panel" style="left:150px;top:600px;width:1620px">
    <div style="font:700 24px D;letter-spacing:.14em;color:#3fc1b0">RANKED CAUSES · CONFIDENCE</div>
    <div class="hyp"><span>Connection leak in the worker</span><div class="track"><div class="fill top" id="h0"></div></div><span class="pct" id="p0">0%</span></div>
    <div class="hyp"><span>Bad settings deploy in the API</span><div class="track"><div class="fill" id="h1"></div></div><span class="pct" id="p1">0%</span></div></div></div>

<div class="sc" id="prove">
  <div class="m" style="top:180px">${words("Fixes it")} ${words("safely.", "lime")}</div>
  <div style="position:absolute;left:150px;top:330px">
    <div class="chip" id="c0"><b>FIX 1</b>Stop the job leaking connections</div>
    <div class="chip" id="c1"><b>FIX 2</b>Undo the bad settings deploy</div>
    <div class="chip" id="c2" style="color:#9db5b0;font-size:32px">Real customer traffic works again · cause truly gone</div></div>
  <svg id="check" width="440" height="440" viewBox="0 0 440 440"><circle id="cc" cx="220" cy="220" r="190"/><path id="cp" d="M130 228 L195 292 L315 160"/></svg>
  <div class="stamp" id="stamp">INDEPENDENTLY VERIFIED</div></div>

<div class="sc" id="results">
  <div style="position:absolute;left:150px;top:170px;font:700 26px D;letter-spacing:.16em;color:#3fc1b0">ON 12 NEVER-SEEN FAILURES</div>
  <div class="big" id="count">0%</div>
  <div style="position:absolute;left:150px;top:600px;font:40px BB;color:#c9dad6">fixed by Mend AI · <span class="lime">0</span> healthy parts touched</div>
  <div class="bars">
    <div class="bar"><span>Do nothing</span><div class="track"><div class="fill" data-v="0"></div></div><span class="pct">0%</span></div>
    <div class="bar"><span>Restart all</span><div class="track"><div class="fill" data-v="17"></div></div><span class="pct">17%</span></div>
    <div class="bar"><span>Rule checklist</span><div class="track"><div class="fill" data-v="25"></div></div><span class="pct">25%</span></div>
    <div class="bar" style="font-family:BB;color:#fff"><span>Mend AI</span><div class="track"><div class="fill top" data-v="96"></div></div><span class="pct lime">96%</span></div></div></div>

<div class="sc" id="end">
  <div style="position:absolute;left:150px;top:300px;font:700 220px/0.9 D;letter-spacing:.04em" id="logo">${"MEND".split("").map((c, i) => `<span class="w${i > 1 ? " lime" : ""}">${c}</span>`).join("")}</div>
  <div class="m" style="top:540px;font-size:44px;max-width:1000px">${words("Agents that bring failing systems back.")}</div>
  <div class="m" style="top:690px;font-size:40px">${words("Proof, not promises.", "lime")}</div>
  <div style="position:absolute;left:150px;top:800px;font:32px M;color:#c6f24e" id="url">cisntsharp420.github.io/Mend/docs/mend.html</div>
  <div style="position:absolute;left:150px;top:860px;font:26px B;color:#9db5b0" id="who">Naif Alanazi · HUMAIN hackathon · Challenge 1</div></div>

<div id="wipe"></div><div id="cap"></div><div id="prog"></div>
<script>
const T = ${JSON.stringify(T)}, DUR = ${DUR}, CAPTIONS = ${CAPTIONS};
const cl = (x) => Math.max(0, Math.min(1, x));
const ease = (x) => 1 - Math.pow(1 - cl(x), 3);
const easeIO = (x) => (x = cl(x), x < .5 ? 4 * x * x * x : 1 - Math.pow(-2 * x + 2, 3) / 2);
const $ = (s) => document.querySelector(s);
const kinetic = (root, u, start, step = 0.11) => root.querySelectorAll(".w").forEach((el, i) => {
  const k = ease((u - start - i * step) / 0.45);
  el.style.opacity = k; el.style.transform = "translateY(" + (1 - k) * 46 + "px)"; el.style.filter = "blur(" + (1 - k) * 8 + "px)";
});
// ECG path: a heartbeat that flatlines and turns red
const beats = [];
for (let x = 0; x <= ${W}; x += 4) {
  const ph = x % 360; let y = 130;
  if (x < 1250) { if (ph > 150 && ph < 175) y = 130 - (ph - 150) * 4; else if (ph >= 175 && ph < 200) y = 30 + (ph - 175) * 8; else if (ph >= 200 && ph < 220) y = 230 - (ph - 200) * 5; }
  beats.push((x ? "L" : "M") + x + " " + y);
}
$("#ecgline").setAttribute("d", beats.join(" "));
const ecgLen = $("#ecgline").getTotalLength();
const edges = [...document.querySelectorAll(".edge")];
const scene = (id) => T.find((s) => s.id === id);

window.render = (t) => {
  const ph = (t / DUR) * Math.PI * 2;
  document.querySelectorAll(".slab").forEach((el) => {
    const i = +el.dataset.i, s = scene("end"), inEnd = s ? easeIO((t - s.start) / 1.2) : 0;
    const x = 1180 + i * 92 + Math.sin(ph + i * .5) * 18 + 260 * (1 - inEnd) * (t > 1 ? 1 : 0);   // slide aside mid-video, return at the end
    const y = -330 + i * 128 + Math.cos(ph + i * .4) * 22;
    el.style.transform = "translate(" + x + "px," + y + "px) rotate(-38deg) skewX(8deg)";
    el.style.opacity = (t < 1 ? 1 : 0.32 + 0.68 * inEnd) * [.55,.7,.8,.88,.92,.95,.9,.75,.6][i];
  });
  let cap = "", capO = 0;
  T.forEach((s, k) => {
    const el = document.getElementById(s.id), u = t - s.start, d = s.end - s.start;
    const o = cl(Math.min(u / 0.35 + (k === 0 ? 1 : 0), (d - u) / 0.35 + (k === T.length - 1 ? 1 : 0)));
    el.style.opacity = t >= s.start && t < s.end + (k === T.length - 1 ? 1 : 0) ? o : 0;
    if (t >= s.start && t < s.end && s.id !== "end") { cap = s.line; capO = cl(Math.min((u - 0.2) / 0.3, (d - u) / 0.3)); }
    if (o <= 0) return;
    if (s.id === "hook") {
      const k2 = ease(u / (d * 0.75)), line = $("#ecgline");
      line.style.strokeDasharray = ecgLen; line.style.strokeDashoffset = ecgLen * (1 - k2);
      line.style.stroke = k2 > 0.62 ? "#ff8a78" : "#3fc1b0";
      kinetic(el, u, 0.3);
    } else if (s.id === "problem") {
      kinetic(el, u, 0.15, 0.13);
      document.querySelectorAll("#problem .node").forEach((n, i) => { const k3 = ease((u - i * 0.12) / 0.4); n.style.opacity = k3; n.style.transform = "translateY(" + (1 - k3) * 20 + "px)"; });
      const down = u > d * 0.35;
      $('[data-k="db"]').classList.toggle("down", down);
      edges.forEach((e, i) => { e.style.strokeDasharray = 600; e.style.strokeDashoffset = 600 * (1 - ease((u - 0.4 - i * 0.1) / 0.5)); });
      document.querySelectorAll("#problem .dot").forEach((c) => {
        const e = edges[+c.dataset.e], L = e.getTotalLength(), into = [2, 4].includes(+c.dataset.e);
        let f = ((u * 0.55 + +c.dataset.j / 3) % 1);
        if (down && into) f = Math.min(f, 0.78);
        const p = e.getPointAtLength(L * f); c.setAttribute("cx", p.x); c.setAttribute("cy", p.y);
        c.style.opacity = u > 0.9 ? (down && into ? 0.9 : 1) : 0; c.style.fill = down && into ? "#ff8a78" : "#c6f24e";
      });
      const r = $("#ring"), pu = down ? ((u - d * 0.35) % 1) : 0;
      r.setAttribute("r", 60 + pu * 70); r.style.opacity = down ? 1 - pu : 0;
    } else if (s.id === "meet") {
      kinetic(el, u, 0.1);
      $("#log").style.transform = "translateY(" + (-ease((u - 0.8) / (d * 0.5)) * 92) + "px)";
      const a = ease((u - d * 0.5) / 1.0), b = ease((u - d * 0.5 - 0.35) / 1.0);
      $("#h0").style.width = 85 * a + "%"; $("#p0").textContent = Math.round(85 * a) + "%";
      $("#h1").style.width = 76 * b + "%"; $("#p1").textContent = Math.round(76 * b) + "%";
    } else if (s.id === "prove") {
      kinetic(el, u, 0.1);
      [0, 1, 2].forEach((i) => { const k3 = ease((u - 0.6 - i * 0.55) / 0.4); const c = document.getElementById("c" + i); c.style.opacity = k3; c.style.transform = "translateX(" + (1 - k3) * -60 + "px)"; });
      const cc = $("#cc"), cp = $("#cp"), lc = cc.getTotalLength(), lp = cp.getTotalLength();
      cc.style.strokeDasharray = lc; cc.style.strokeDashoffset = lc * (1 - ease((u - 1.6) / 0.8));
      cp.style.strokeDasharray = lp; cp.style.strokeDashoffset = lp * (1 - ease((u - 2.2) / 0.5));
      const ks = ease((u - 2.7) / 0.35), st = $("#stamp"); st.style.opacity = ks; st.style.transform = "scale(" + (1.5 - 0.5 * ks) + ")";
    } else if (s.id === "results") {
      const k3 = ease((u - 0.3) / 1.6); $("#count").textContent = Math.round(96 * k3) + "%";
      document.querySelectorAll("#results .fill").forEach((f, i) => { f.style.width = +f.dataset.v * ease((u - 0.5 - i * 0.25) / 1.2) + "%"; });
    } else if (s.id === "end") {
      kinetic(el, u, 0.25, 0.09);
      const ku = ease((u - 1.6) / 0.5); $("#url").style.opacity = ku; $("#who").style.opacity = ease((u - 1.9) / 0.5);
    }
  });
  // diagonal wipe that covers each cut
  let wx = -2000;
  T.slice(1).forEach((s) => { const k = (t - (s.start - 0.3)) / 0.6; if (k >= 0 && k <= 1) wx = -1300 + easeIO(k) * 3600; });
  const wp = $("#wipe"); wp.style.display = wx > -2000 ? "block" : "none"; wp.style.left = wx + "px";
  $("#mark").style.opacity = t < T[0].end || t >= T[T.length - 1].start ? 0 : 1;
  $("#cap").textContent = cap; $("#cap").style.opacity = CAPTIONS ? capO : 0;
  $("#prog").style.width = (t / DUR) * 100 + "%";
};
</script></body></html>`;

(async () => {
  const b = await chromium.launch();
  const p = await b.newPage({ viewport: { width: W, height: H } });
  await p.setContent(HTML);
  await p.evaluate(() => document.fonts.ready);
  const args = ["-y", "-loglevel", "error", "-f", "image2pipe", "-framerate", String(FPS), "-i", "-"];
  if (AUDIO) args.push("-i", AUDIO);
  args.push("-c:v", "libx264", "-preset", "medium", "-crf", "19", "-pix_fmt", "yuv420p");
  if (AUDIO) args.push("-c:a", "aac", "-b:a", "192k", "-shortest");
  args.push("-movflags", "+faststart", OUT);
  const ffm = spawn("ffmpeg", args, { stdio: ["pipe", "inherit", "inherit"] });
  const done = new Promise((res, rej) => ffm.on("close", (c) => (c === 0 ? res() : rej(new Error("ffmpeg exited " + c)))));
  const frames = Math.round(DUR * FPS);
  for (let i = 0; i < frames; i++) {
    await p.evaluate((t) => window.render(t), i / FPS);
    const buf = await p.screenshot({ type: "jpeg", quality: 92 });
    if (!ffm.stdin.write(buf)) await new Promise((r) => ffm.stdin.once("drain", r));
    if (STILLS) T.forEach((s) => { if (i === Math.round((s.start + (s.end - s.start) * 0.8) * FPS)) fs.writeFileSync(path.join(path.dirname(OUT), "still-" + s.id + ".jpg"), buf); });
    if (i % 150 === 0) process.stdout.write(`frame ${i}/${frames}\n`);
  }
  ffm.stdin.end();
  await done;
  await b.close();
  console.log("wrote", OUT, Math.round(fs.statSync(OUT).size / 1024) + " KB");
})();
