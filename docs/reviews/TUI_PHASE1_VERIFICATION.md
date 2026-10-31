# Silica TUI — Phase 1 Verification Review

**Requested by:** owner review instruction (`paste-1-5.md`)
**Commit under review:** `09368e9d2c43985d10982b99335cfb71d387f27a`
**Repository:** `sufiyan-sabeel/silica` (public, default branch `main`)
**Reviewed:** 2026-10-29
**Verdict:** the reported **728-test result reproduces exactly** (721 passed + 7 skipped), and the terminal-cleanup work is genuinely tested for the two paths it claims. I found **4 cleanup defects** and **6 verified interaction gaps** that the suite does not cover.

> **Note added at publication.** `main` has since advanced past the reviewed
> commit to `cc6833c` ("0.8.0: tests/test_voice_models.py"). `silica/tui/__init__.py`,
> `silica/tui/natives_tui.py` and `tests/test_tui_widgets.py` are **byte-identical**
> between the two commits — the intervening work is voice engines, capabilities,
> docs and install tests — so every finding below still holds at the current head.
> The probes were re-run against `cc6833c` and produced identical results.

Nothing was changed: no version bump, no tags, no commits, no pushes, no packages, no GitHub release. All findings below come from a read-only snapshot of the commit, run in an isolated sandbox.

---

## 1. The commit exists — and its diff is test-only

| Check | Result |
|---|---|
| Repository exists and is public | Yes — `sufiyan-sabeel/silica`, default branch `main` |
| Commit `09368e9…` exists | Yes |
| Commit is the head of `main` | Yes (branches-with-head returns `main`; `main` = `09368e9d2c43`) |
| Author / date | `sufiyan-sabeel`, 2026-10-29T15:02:11Z |
| Parent | `e2a4396ec7fe` |
| Files changed | **1** — `tests/test_tui_widgets.py`, **+348 / −0** |
| Message | `0.8.0: tests/test_tui_widgets.py` |

**The commit under review adds one test file and nothing else.** The TUI implementation it is nominally reviewing lives in earlier commits on the same branch:

```
09368e9  0.8.0: tests/test_tui_widgets.py        <- the commit to verify
e2a4396  0.8.0: examples/tui_settings.sc
06d47cc  0.8.0: examples/tui_dashboard.sc
12970d6  0.8.0: tests/test_optimizer.py
36b7818  0.8.0: silica/tui/natives_tui.py
dc202aa  0.8.0: silica/tui/__init__.py
ded6789  TUI framework: exception-safe cleanup, exact colour, five new widgets
ff82947  0.8.0: tests/test_tui_render.py
39248a1  0.8.0: examples/tui_calculator.sc
…
```

So "TUI Phase 1" is a series of commits, not a single one. Anyone reviewing only `09368e9` would see tests and no implementation.

What that test file actually covers (23 test functions): progress bars, spinner/status, radio groups, textareas, `CleanupTests`, and exact-colour palette behaviour. `CleanupTests` is a genuine pty test that runs real Silica programs through `silica run --allow-tui` and asserts the terminal is restored after (a) a runtime error and (b) a clean exit — that claim is real and passes.

## 2. Branch and working-tree state

| Check | Result |
|---|---|
| Present on the intended branch | Yes — `main`, at the tip |
| Pushed | Yes — repository `pushed_at` = 2026-10-29T15:02:11Z, and the SHA is `main`'s head |
| Other branches | `feature/global-installer` (0 ahead, **103 behind** — stale), 3 Dependabot branches |
| Unmerged work elsewhere | None: the feature branch has no commits main lacks |
| Local working tree | **Not verifiable here.** This review used a read-only snapshot of the commit; no `.git` directory and no local working tree exist in my environment. I cannot report on uncommitted local changes on the developer's machine. |

## 3. Independent test run: 728 reproduces

```bash
pip install pytest build wheel setuptools      # dev extras
python -m pytest tests -q
# 721 passed, 7 skipped, 865 subtests passed in 96.87s
```

721 + 7 = **728**, matching the reported figure. 865 parameterised subtests also pass.

Two environment gaps had to be closed first — neither is a code defect:

1. **2 failures** (`test_install.py::ScriptTests::test_scripts_are_executable_in_the_checkout` for `install.sh` / `uninstall.sh`) were caused by my snapshot losing the executable bit. The repository stores them as mode **`100755`** (verified via the git tree API), so the committed state is correct. Rerunning from a copy with `chmod +x` removed both failures.
2. **12 errors** (`test_install.py::EndToEndTests`) were `RuntimeError: could not build a wheel; is the 'build' package installed` — the suite raises rather than skips when `build`/`setuptools` are missing, which is the right choice (a silent skip would hide a broken installer), but it means a bare checkout reports 12 errors until `pip install .[dev]` is run.

The 7 skips are honest and explicit: 5 GUI tests (`needs a display; run under xvfb-run`) and 2 voice tests (`set SILICA_VOICE_TESTS=1 with engines installed`).

## 4. atexit / terminal cleanup review

Method: seven scenarios executed inside a **real pty**, each in its own process, with the tty inspected afterwards for (a) alternate-screen enter/leave balance, (b) `ECHO`/`ICANON` restoration, (c) whether the cursor is shown again, and (d) the process exit status. Probe source: `tools/probes/probe_cleanup.py` and `probe_cleanup_child.py`.

| Scenario | Result | Evidence |
|---|---|---|
| Normal exit via `tui.close` | **Pass** | alt screen 1 enter / 1 leave, tty sane, cursor restored, `_OPEN_APPS` empty |
| Repeated cleanup (`close` × 3) | **Pass** | second and third calls are no-ops, no exception, state consistent |
| Uncaught exception **inside** `run()` | **Pass** | original `ValueError` propagates unchanged; `run()`'s `finally` restores the terminal; 1/1, tty sane |
| Uncaught exception **outside** `run()` | **Pass** | atexit restored the terminal (1/1, tty sane) and the process still exited 1 with its own message |
| **Multiple screens** | **Defect D3** | two apps can be open at once (`_OPEN_APPS` = 2), but closing the first calls `curses.endwin()`, tearing the terminal down under the second (observed enter/leave 2/2 with the leave happening mid-session) |
| **Partial initialisation** | **Defect D1** | `initscr()` succeeded, the next step failed: `TUIError` raised, but the **tty was left with `ECHO`/`ICANON` off** (`tty_sane=False`) |
| **Teardown itself raises** | **Defect D2** | `endwin()` raising replaced the in-flight `ValueError` with `RuntimeError: endwin failed`, and left the alt screen entered (1 enter / 0 leave, `LEAKED=True`) |

### The four defects, precisely

**D1 — partial initialisation leaks terminal state.**
In `_open()`, `app._screen = screen` is assigned *after* the `try` block. If any step after `initscr()` raises (`noecho`, `cbreak`, `keypad`, `start_color`), the function raises `TUIError` while the terminal is already in curses mode, `app._screen` is still `None`, so neither `_close()` nor the atexit hook can clean it up. Evidence: `partial_init` left the pty with echo and canonical mode disabled. Fix: wrap the body so that a failure calls `curses.endwin()` (best effort) before raising, or assign `app._screen` immediately after `initscr()` and register before the remaining steps.

**D2 — a teardown failure masks the original exception.**
`_close()` uses `try: … finally: …` with no `except`, so if `nocbreak()`/`echo()`/`endwin()` raises, that new exception replaces whatever was propagating and the remaining restore steps are skipped. Evidence: `cleanup_raises` produced `RuntimeError: endwin failed` instead of `ValueError: original failure`, with the alt screen left entered. This is exactly the "does cleanup preserve the original exception" question — **today the answer is no**. Fix: catch per-step failures, always attempt `endwin()`, and never let teardown raise out of `_close`.

**D3 — closing one app tears down every other open app.**
`_OPEN_APPS` is a list and multiple apps may be registered, but curses' terminal state is global: `_close(first)` calls `curses.endwin()` while `second` is still open, so the second app's terminal is destroyed. Either support only one live screen (raise a clear `TUIError` when a second app opens while one is live) or refcount: only call `endwin()` when the last registered app closes. Right now the API allows a configuration the backend cannot honour.

**D4 — restore failures at exit are invisible.**
`_restore_all()` swallows every exception (`except Exception: pass`). Combined with D2, a user can end up with a wrecked terminal and no diagnostic at all. At minimum, write the failure to stderr (curses has already been torn down at that point, so it is safe).

Positive findings worth recording: the single-source-of-truth focus model is real (`App.focus_index` + `App.focused()`), `close()` is idempotent, and both exception paths do restore the terminal in the ordinary case.

## 5. Widget keyboard interaction and colour fallback

Method: the real `tui.poll()` event path driven by an injected screen and a fake curses backend (so `_key_name` runs unmodified), plus the palette exercised against capability-different fake terminals. Probe source: `tools/probes/probe_widgets.py`. **43 probes: 37 pass, 0 fail, 6 verified gaps.**

Verified working:

| Behaviour | Evidence |
|---|---|
| Up/Down move focus, and wrap at both ends | focus identity checked, not label text |
| Enter activates the focused button **exactly once** | `take_pressed()` returns the label once, `""` on a second call — no duplicate action from one keypress |
| Space activates | yes |
| Disabled widget is excluded from focus and never activates | not in `focusables()`; `press()` refuses it |
| Radio Left/Right changes selection | `selected` moves 0→1→0 |
| Escape reported as `"escape"`; resize updates `app.size` | yes |
| Empty layout: no focus, keys do not raise | yes |
| Removing the focused widget does not raise | focus index re-modulos safely |
| Colour parsing (`#RRGGBB`, names, invalid, default) | 4/4 |
| 256-colour mapping incl. the grey ramp | red→196, green→46, blue→21, grey→244 |
| Basic (8/16-colour) terminals map into 0..15 | index 2 for the theme accent |
| No-colour terminals fall back to attribute 0 | `mode == "none"`, `pair() == 0` |
| True-colour terminals redefine a palette slot | `init_color(16, 271, 776, 690)` for the theme accent |
| Pair-table exhaustion falls back to attribute 0 | yes |
| Every style token maps to a pair | 14/14 |
| Theme override reaches the rendered colour | `#FF0000` → `(1000, 0, 0)` vs default `(271, 776, 690)` |

Verified **gaps** (behaviour the brief asks for and the code does not have):

| Gap | Observed |
|---|---|
| **Tab does not move focus** | `_key_name` emits `"tab"`, but `poll()` has no `"tab"` branch, so nothing happens |
| **Shift+Tab does nothing** | `KEY_BTAB` is not in `KEY_NAMES`; the raw name `"KEY_BTAB"` leaks through and no `"backtab"` branch exists |
| **Text inputs have no cursor** | Left/Right are handled only for `radio`; typing always appends (`"abcd"` + Left + `X` → `"abcdX"`) |
| **Delete clears the whole field** | `KEY_DC` sets `node.value = ""` rather than deleting one character |
| **PageUp/PageDown/Home/End do nothing** | names are produced but never handled |
| **Lists never scroll** | `node.scroll` is only ever *read* (`__init__.py:470`); nothing increments it, so a 50-item list renders clipped to its box (24 lines) with no way to reach the rest |

No test in the suite mentions `scroll`, `tab`, `backtab` or `KEY_DC` — these gaps are untested rather than regressions.

## 6. Android / Termux test checklist

Nothing below was verified on a device. Column 3 says what I could establish in this Linux sandbox.

| # | Check | How | Verified here? |
|---|---|---|---|
| 1 | `pkg install python` and `python -m silica --version` works on Termux | `pip install .` in Termux, then `silica --version` | **No** — needs a device |
| 2 | `silica run examples/tui_demo.sc --allow-tui` draws and quits on `q` | run in Termux | **No** — needs a device |
| 3 | Alt screen and cursor restored after `q` | `tui_demo.sc`, then check the prompt behaves normally | **Partly** — pty equivalent passes on Linux |
| 4 | Terminal restored after a **runtime error** mid-TUI | modify an example to raise, run, check the prompt | **Partly** — pty equivalent passes |
| 5 | Colours: Termux advertises 256 colours | `silica` program printing `tui.colour_mode(app)` | **No** — device; sandbox reports `256` |
| 6 | Colours on a 16-colour / no-colour terminal | `TERM=vt100`, `TERM=dumb` | **No** — device/emulator |
| 7 | Hardware keyboard: arrows, Enter, Space, Esc | interactive | **Partly** — key handling verified with an injected backend |
| 8 | Soft keyboard (Termux extra keys row) sends arrows/Enter | interactive | **No** — needs a device |
| 9 | Resize / rotation triggers `KEY_RESIZE` and re-layout | rotate the device or resize the Termux window | **No** — device |
| 10 | Narrow terminal (40 columns) layout does not crash | `COLUMNS=40` | **Partly** — can be run here |
| 11 | Long list clipping is understood as a limitation (no scrolling yet) | open a list longer than the screen | **Yes** — reproduced (gap above) |
| 12 | Touch/mouse events where the terminal forwards them | tap/click in Termux | **No** — device |
| 13 | Unicode box-drawing renders as lines, not boxes | look at a panel border | **No** — needs the device's font |
| 14 | Battery/CPU: idle loop does not spin | run `tui_demo` idle, check `top` | **No** — device |
| 15 | `pip install .` inside Termux produces a working `silica` | run `silica --version`, `silica run examples/hello.sc` | **No** — device |

Checks 1, 2, 5, 6, 8, 9, 12, 13, 14 and 15 need a physical Android device (or at minimum an Android emulator with a real Termux install). Checks 3, 4, 7 and 10 have Linux-pty equivalents that pass; passing them here is **not** evidence that they pass on Android.

## 7. Regressions, incomplete work, and report discrepancies

**Regressions:** none found. The full suite passes at this commit. I did not run a baseline at an earlier commit, so I cannot claim "no regression relative to 0.8.0" — only that nothing in the current suite fails. Note that the commit under review changes only a test file, so it cannot regress behaviour by construction; the TUI behaviour changed in the preceding commits.

**Incomplete work (verified, not speculation):**

1. Tab / Shift+Tab focus traversal (§5).
2. Text-input cursor, insertion at position, selection; Delete semantics (§5).
3. List/container scrolling — `node.scroll` is never incremented, so scrollable content does not exist despite the field (§5).
4. Multiple simultaneously open screens (D3).
5. Terminal restore when initialisation fails part-way (D1).
6. Terminal restore and exception preservation when teardown itself fails (D2, D4).

**Discrepancies I can evidence:**

* **Commit subjects say `0.8.0:` while the project is `0.9.0`.** `pyproject.toml`, `silica/__init__.py` and `CHANGELOG.md` all agree on `0.9.0`; only the commit-message prefixes are stale. Cosmetic, but it makes the history misleading about which release a change belongs to.
* **The named commit is test-only.** A review that inspected only `09368e9` would not see the implementation at all.
* **`tui.render` is documented as "draw one frame; returns the lines"** (`docs/STANDARD_LIBRARY.md:302`). In fact `render()` is a **no-op for display unless a terminal is already open** — only `tui.poll` initialises curses. A program calling only `tui.render` never paints. The behaviour is defensible; the documentation does not say it.
* **I do not have the implementation report text**, so I cannot diff its claims line by line. I verified the two claims that are testable from the outside — the commit's existence/contents and the 728-test figure — and both hold.

**What I could not verify at all:** anything requiring a physical Android device, a display server (5 GUI tests skip), or voice engines (2 voice tests skip); and the developer's local working tree, which is not present in a snapshot.

## 8. Reproducing these results

```bash
# 1. get the exact commit
#    (any clone works; this is the SHA the review names)
git clone https://github.com/sufiyan-sabeel/silica.git && cd silica
git checkout 09368e9d2c43985d10982b99335cfb71d387f27a

# 2. the suite as the project intends it
python -m pip install -e ".[dev]"
python -m pytest tests -q          # 721 passed, 7 skipped, 865 subtests

# 3. the probes delivered with this report (`tools/probes/`)
python tools/probes/probe_widgets.py   # 43 probes: 37 pass, 0 fail, 6 gaps
python tools/probes/probe_cleanup.py   # 7 pty scenarios; D1/D2/D3 reproduce
```

The probes live in `tools/probes/` and resolve the checkout from their own
location (`<repo>/tools/probes/…`), so no path editing is needed. Set
`SILICA_ROOT` if you run them from somewhere else.

## 9. Recommendations, ranked — awaiting approval

1. **Fix D2 first** (`_close` must never raise or skip restore steps), then **D1** (restore on partial init). These are the two ways a user's terminal gets wrecked, and both are small, local changes in `_open`/`_close`.
2. **Decide the multi-screen contract** (D3): either one live screen with a clear error, or refcounted `endwin()`.
3. **Add the missing key branches**: `tab`/`backtab` → `focus_next(±1)`, `home`/`end`/`pageup`/`pagedown` → list scrolling, and give `KEY_DC` delete-at-cursor semantics instead of clearing the field.
4. **Implement list scrolling** (`node.scroll` is currently inert) or remove the field and document lists as clipped.
5. **Add regression tests for each**: partial init, teardown failure, second screen, Tab, Delete, scrolling — my probes can be lifted into `tests/` almost verbatim.
6. **Correct the `tui.render` documentation** and normalise the `0.8.0:`/`0.9.0` commit labels going forward.
7. **Run the Termux checklist (§6) on the device** before any release conversation; 10 of the 15 checks cannot be settled from a Linux sandbox.

No changes were made to the repository, the version, or any branch. Say the word and I will implement items 1–6 as a patch set on a branch (not pushed) for your review.
