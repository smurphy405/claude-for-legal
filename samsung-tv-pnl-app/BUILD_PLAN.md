# Samsung TV App: Live CNBC + Scrolling P&L

Build plan for a custom app that runs directly on the office Samsung TV. It
shows the live CNBC channel the TV already receives, with a scrolling P&L
ticker and panels on the same screen. Buttons on the normal TV remote switch
between layouts.

**No Fire Stick or extra box.** The app is installed on the TV itself and uses
the TV's own channel feed.

---

## 1. How it works

```
 ┌──────────────────────────── Samsung TV ────────────────────────────┐
 │                                                                     │
 │   CNBC (antenna/cable into TV, or cable box on HDMI)                │
 │        │                                                            │
 │        ▼                                                            │
 │   ┌──────────────────────────┐   ┌──────────────┐                   │
 │   │  Live TV window (CNBC)   │   │  Fund panel  │  ◄── our app      │
 │   │  sized/placed by our app │   │  Day / MTD   │      (HTML + JS)  │
 │   └──────────────────────────┘   └──────────────┘                   │
 │   ┌─────────────────────────────────────────────────────┐           │
 │   │ ◄◄ AAPL +12.5k  NVDA -3.2k  SPX +0.4%  Fund +125k ◄◄│ ticker    │
 │   └─────────────────────────────────────────────────────┘           │
 └───────────────────────────────▲─────────────────────────────────────┘
                                 │  every 5 seconds: GET /api/pnl (office network)
                                 │
                    ┌────────────┴────────────┐
                    │   P&L service           │  small program on an office PC
                    │   (read only)           │  or server
                    └────────────▲────────────┘
                                 │  pulls positions and P&L
                    ┌────────────┴────────────┐
                    │ Broker / prime broker / │
                    │ OMS / spreadsheet       │
                    └─────────────────────────┘
```

There are two pieces to build:

| Piece | What it is | Where it runs |
|---|---|---|
| **TV app** | A Samsung (Tizen) web app: HTML, CSS, JavaScript. Shows the live channel in a window, draws the ticker and panels, handles the remote. | On the TV |
| **P&L service** | A small read-only web service. Pulls P&L from wherever it lives today and serves it as simple JSON. | Any office PC or server on the same network as the TV |

The TV never holds broker logins. It only reads numbers from the P&L service.

---

## 2. Screen layouts

The TV screen is treated as 1920 x 1080.

### Layout 1: CNBC full screen
CNBC fills the screen. No overlay. Normal TV viewing.

### Layout 2: CNBC + P&L (default)
```
┌─────────────────────────────────────────┬────────────┐
│                                         │ FUND       │
│            CNBC live                    │ Day  +125k │
│            1600 x 900                   │ MTD  +1.2m │
│                                         │ YTD  +8.4m │
│                                         │ Top/Bottom │
│                                         │ movers     │
├─────────────────────────────────────────┴────────────┤
│ ◄◄ scrolling ticker: positions, P&L, index levels ◄◄ │  180 px
└──────────────────────────────────────────────────────┘
```
- CNBC window: x 0, y 0, 1600 x 900 (keeps 16:9, no stretching)
- Right panel: 320 px wide, fund totals plus top and bottom movers
- Bottom band: 180 px tall, scrolling ticker across the full width

### Layout 3: Full P&L dashboard
Full screen P&L: positions table, fund totals, sector or strategy breakdown.
CNBC continues in a small corner window (480 x 270) with audio still playing.

### Privacy mode (any layout)
One button blanks all P&L numbers (shows "P&L hidden") for when visitors are
in the room. CNBC keeps playing.

---

## 3. Remote control mapping

Newer Samsung remotes have no number pad, so the main controls use the arrow
and OK buttons that every remote has. Number keys work as shortcuts on remotes
that have them.

| Button | Action |
|---|---|
| Right / OK | Next layout |
| Left | Previous layout |
| Up | Privacy mode on/off |
| Down | Status overlay (data age, connection, last update time) |
| 1 / 2 / 3 | Jump straight to layout 1, 2 or 3 |
| Channel up/down | Change channel (only when CNBC comes from the TV's own tuner) |
| Back | Ignored, so the app does not close by accident |
| Volume / Mute | Handled by the TV as normal |
| Home / Exit | Leaves the app (TV default) |

---

## 4. The TV app

### 4.1 Tools
- **Tizen Studio** (Samsung's free developer tool) on a Windows or Mac PC, with
  the **TV Extensions** and **Samsung Certificate Extension** packages
  installed through its Package Manager. Samsung's VS Code extension is an
  alternative.
- A free **Samsung developer account** (used to create the signing
  certificate).

### 4.2 Project structure
```
samsung-tv-pnl-app/
  tv-app/
    config.xml          # app ID, permissions
    index.html
    css/style.css       # layouts, ticker animation
    js/config.js        # P&L service URL, API key, video source, refresh rate
    js/video.js         # live TV window: pick source, place and resize it
    js/keys.js          # remote control handling
    js/pnl.js           # fetch P&L, render ticker and panels, stale detection
    js/main.js          # startup, layout switching, resume handling
    icon.png
  pnl-service/
    app.py              # web service (Python / FastAPI)
    adapters/           # one file per data source (broker API, CSV drop, Excel)
    .env.example        # credentials live here, never on the TV
  BUILD_PLAN.md
```

### 4.3 Permissions (`config.xml`)
```xml
<tizen:privilege name="http://tizen.org/privilege/tv.window"/>      <!-- show live TV in a window -->
<tizen:privilege name="http://tizen.org/privilege/tv.channel"/>     <!-- change channel (tuner only) -->
<tizen:privilege name="http://tizen.org/privilege/tv.inputdevice"/> <!-- remote keys -->
<tizen:privilege name="http://tizen.org/privilege/internet"/>       <!-- reach the P&L service -->
<access origin="*" subdomains="true"/>
<tizen:profile name="tv-samsung"/>
```

### 4.4 Showing the live channel
Samsung's **TVWindow API** places the live TV picture (tuner or HDMI input) in
a rectangle on screen. With `BEHIND`, the video sits under the app's page, so
the page background is transparent where the video shows and the panels and
ticker are drawn on top.

```js
// js/video.js
// CONFIG.videoSource: 'TV' for antenna/cable into the TV, 'HDMI' for a cable box
// CONFIG.hdmiPort:    which HDMI port the cable box is on (e.g. 1)

var LAYOUT_RECTS = {
  full:      ['0px', '0px', '1920px', '1080px'],
  ticker:    ['0px', '0px', '1600px', '900px'],
  dashboard: ['1420px', '790px', '480px', '270px']   // corner window
};

function startLiveTv(layout) {
  tizen.systeminfo.getPropertyValue('VIDEOSOURCE', function (info) {
    var src = info.connected.filter(function (s) {
      return s.type === CONFIG.videoSource &&
             (s.type !== 'HDMI' || s.number === CONFIG.hdmiPort);
    })[0];
    tizen.tvwindow.setSource(src, function () {
      placeVideo(layout);
    }, onVideoError, 'MAIN');
  }, onVideoError);
}

function placeVideo(layout) {
  tizen.tvwindow.show(function () {}, onVideoError,
                      LAYOUT_RECTS[layout], 'MAIN', 'BEHIND');
}
```

### 4.5 Remote control handling
```js
// js/keys.js
['1', '2', '3', 'ChannelUp', 'ChannelDown'].forEach(function (k) {
  try { tizen.tvinputdevice.registerKey(k); } catch (e) {}
});

document.addEventListener('keydown', function (e) {
  switch (e.keyCode) {
    case 39: case 13: nextLayout(); break;          // Right, OK
    case 37: prevLayout(); break;                   // Left
    case 38: togglePrivacy(); break;                // Up
    case 40: toggleStatus(); break;                 // Down
    case 49: setLayout('full'); break;              // 1
    case 50: setLayout('ticker'); break;            // 2
    case 51: setLayout('dashboard'); break;         // 3
    case 427: channelUp(); break;                   // Channel up (tuner only)
    case 428: channelDown(); break;                 // Channel down (tuner only)
    case 10009: e.preventDefault(); break;          // Back: ignore
  }
});
```

### 4.6 P&L display
```js
// js/pnl.js
function poll() {
  fetch(CONFIG.pnlUrl, { headers: { 'X-Api-Key': CONFIG.apiKey } })
    .then(function (r) { return r.json(); })
    .then(function (data) { render(data); scheduleNext(); })
    .catch(function () { markStale(); scheduleNext(); });
}
function scheduleNext() { setTimeout(poll, CONFIG.refreshMs); }  // default 5000
```
- **Ticker:** a CSS `translateX` animation over two copies of the ticker
  content, so it loops with no gap. Speed is set in `config.js`.
- **Colors:** green for gains, red for losses, grey when unchanged.
- **Stale data:** if `asOf` is more than 30 seconds old, or the service cannot
  be reached, show an amber **STALE** badge and the time of the last good
  update. Never show old numbers as if they were live.
- **Market closed:** show the closing P&L with a "Close" label.

### 4.7 Staying on screen
- When the TV is turned off and on, or the app is reopened, re-run
  `startLiveTv()` on the `visibilitychange` event so the video window comes
  back.
- TV settings: turn off **Auto Power Off** and eco power saving. If the model
  has **Autorun Last App** (Settings, General, Smart Features), turn it on so
  the app reopens when the TV powers on.
- **Burn-in (OLED models only):** the fund panel and headers move a few pixels
  every few minutes. The ticker already moves.

---

## 5. The P&L service

A small read-only web service. Python with FastAPI is assumed here; Node.js
works just as well.

### 5.1 What it does
1. Every few seconds, pulls positions and P&L from the source system through
   an **adapter** (one per source).
2. Normalizes the numbers into one format.
3. Serves the latest snapshot at `GET /api/pnl`.

### 5.2 Data source adapters
Which adapter gets built depends on where P&L lives today:

| Source | How the adapter gets data |
|---|---|
| Interactive Brokers | TWS / IB Gateway API or Client Portal API |
| Prime broker | Their API, or files they drop on SFTP (CSV) |
| OMS / EMS / PMS | The vendor's API or a database read |
| Spreadsheet | Read a shared Excel or CSV file on a schedule |
| Market levels (SPX, 10Y, etc.) | The same source, or a market data feed you already license |

### 5.3 JSON format served to the TV
```json
{
  "asOf": "2026-11-06T14:32:05Z",
  "marketStatus": "open",
  "fund": {
    "nav": 152340000,
    "dayPnl": 125340.12,
    "dayPnlPct": 0.08,
    "mtdPnl": 1210000,
    "ytdPnl": 8420000
  },
  "positions": [
    { "symbol": "AAPL", "qty": 10000, "last": 231.12, "dayPnl": 12500.0, "dayPct": 1.2 },
    { "symbol": "NVDA", "qty": -5000, "last": 141.30, "dayPnl": -3200.0, "dayPct": 0.9 }
  ],
  "markets": [
    { "symbol": "SPX", "last": 5912.4, "chgPct": 0.41 },
    { "symbol": "US10Y", "last": 4.21, "chgBps": -3 }
  ]
}
```
The TV only renders what it gets here, so which fields and positions appear on
screen is controlled entirely in the service.

### 5.4 Service sketch
```python
# pnl-service/app.py
from fastapi import FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import os

app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["GET"],
                   allow_headers=["X-Api-Key"])
API_KEY = os.environ["PNL_API_KEY"]

@app.get("/api/pnl")
def pnl(x_api_key: str = Header(...)):
    if x_api_key != API_KEY:
        raise HTTPException(status_code=401)
    return cache.snapshot()   # refreshed in the background by the active adapter
```

### 5.5 Security
- **Read only.** The service can view P&L and nothing else. It cannot place or
  change trades.
- **Office network only.** No port forwarding and no public internet exposure.
  Optionally allow only the TV's IP address.
- **API key** between the TV and the service. Broker or OMS credentials stay in
  the service's `.env` file, never on the TV.
- **Privacy mode** on the remote for when visitors are in the room.
- Decide up front which numbers are appropriate on a wall screen (for example
  fund level and top movers only, not full position sizes).

---

## 6. Installing the app on the TV

This is done once from a PC on the same network as the TV. Nothing goes
through Samsung's app store.

1. **Install Tizen Studio** on the PC, plus TV Extensions and Samsung
   Certificate Extension from its Package Manager.
2. **Turn on Developer Mode on the TV.** Open **Apps**, then enter **1 2 3 4 5**
   with the remote (on remotes without numbers, use the on-screen number pad).
   Switch Developer Mode **On**, enter the PC's IP address, and restart the TV.
3. **Connect the PC to the TV.** In Tizen Studio's Device Manager, add the TV by
   its IP address (port 26101).
4. **Create the signing certificate.** In Tizen Studio's Certificate Manager,
   create a **Samsung** certificate for **TV**, signing in with the Samsung
   developer account. The distributor certificate is tied to this specific TV.
   In Device Manager, choose **Permit to install applications** for the TV.
5. **Install.** Open the `tv-app` project and click **Run** (or use the command
   line below). The app appears in the TV's app list like any other app.

Command line version, for reinstalling later:
```bash
sdb connect <TV_IP>
tizen build-web -- tv-app
tizen package -t wgt -s <certificate_profile> -- tv-app/.buildResult
tizen install -n PnLWall.wgt -t <TV_DEVICE_NAME> -- tv-app/.buildResult
```

**Upkeep:** a firmware update or an expired certificate can require a
reinstall. That is a five minute job with the steps above. A short install
script and these steps go in the README so anyone in the office can do it.

---

## 7. Build phases

| Phase | Work | Time |
|---|---|---|
| **0. Feasibility test** | A bare-bones app on the actual TV that shows CNBC in a resizable window with HTML drawn on top. Confirms the TV model allows it with a standard certificate. **Go / no-go point.** | 1 to 2 days |
| **1. Layouts and remote** | All three layouts, remote mapping, ticker and panels running on sample data. | 3 days |
| **2. Real P&L** | P&L service connected to the real data source, stale-data handling, privacy mode. | 3 to 5 days (depends on the data source) |
| **3. Hardening** | Recovery after power cycles, Wi-Fi drops and service restarts. Burn-in protection, install script, README. | 2 to 3 days |
| **Total** | | **About 2 to 3 weeks for one developer** |

### Phase 0 checklist
- [ ] App installs and opens on the TV
- [ ] CNBC shows in a window from the correct source (tuner or HDMI)
- [ ] Window resizes between layouts without a long black flash
- [ ] HTML panels and ticker draw on top of the video
- [ ] CNBC audio plays normally
- [ ] Channel up/down works (tuner source only)
- [ ] App comes back with video after the TV is turned off and on

### If Phase 0 fails
If this TV model does not allow an app to show the live channel in a window,
the P&L screens (all plain web code) move unchanged to a small PC on the TV's
HDMI, running a full-screen browser. In that case the live CNBC picture has to
come from a streaming source, such as the cable provider's login on cnbc.com,
rather than the TV's own channel. Phase 0 settles this in the first day or two,
before anything else is built.

---

## 8. Inputs needed to start

1. **TV model number** (sticker on the back, or Settings, Support, About This TV).
2. **How CNBC reaches the TV:** antenna or cable plugged straight into the TV,
   or a cable box on an HDMI port (which one), and the channel number.
3. **Where P&L lives today** (broker, prime broker, OMS, spreadsheet) and how
   often it updates.
4. **What to show on screen:** fund totals, which positions, which market
   levels.
5. **Who can see the screen**, to decide what is appropriate to display and
   whether privacy mode should be the default.
6. **A machine to run the P&L service** (an always-on office PC or a server).
