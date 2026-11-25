"""Browser end-to-end test (Playwright + Chromium) against a live server.

    python3 tests/e2e_browser.py [screenshot_dir]

Starts the app on a random local port with a throwaway database, then drives a real browser through
the core editorial workflow. Uses synthetic data labelled FICTIONAL only. Exits non-zero on failure."""
import os
import sys
import tempfile
import threading

from PIL import Image
from playwright.sync_api import expect, sync_playwright
from werkzeug.serving import make_server

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from elf_archive import create_app, db as dbm  # noqa: E402
from tests.helpers import PASSWORD, make_user, publish_new  # noqa: E402

SHOTS = sys.argv[1] if len(sys.argv) > 1 else None


def main():
    tmp = tempfile.mkdtemp()
    path = os.path.join(tmp, "e2e.db")
    conn = dbm.connect(path)
    dbm.migrate(conn)
    contrib = make_user(conn, "e2e_contrib")
    editor = make_user(conn, "e2e_editor", ["editor"])
    make_user(conn, "e2e_mod", ["moderator"])
    place = publish_new(conn, contrib, editor, "place", {"primary_name": "Testville (FICTIONAL)", "aliases": "Testvil"})
    dup_keep = publish_new(conn, contrib, editor, "person", {"preferred_name": "Testperson Twin (FICTIONAL)", "living_status": "deceased",
                                                             "birth": "c. 2099", "birth_place": place["public_id"]})
    dup_retire = publish_new(conn, contrib, editor, "person", {"preferred_name": "Testperson Twin (FICTIONAL)", "living_status": "deceased",
                                                               "occupation": "Test occupation (fictional)"})
    # For the atlas scenario only: a FICTIONAL place with test-only coordinates, in this throwaway database.
    # (Real records get coordinates only from sources; the development seed never invents any.)
    mapped = publish_new(conn, contrib, editor, "place", {"primary_name": "Testhaven (FICTIONAL)", "latitude": "15.62", "longitude": "39.42",
                                                         "coord_precision": "approximate", "coord_note": "Test-only location (FICTIONAL)."})
    harbour = publish_new(conn, contrib, editor, "event", {"title": "Test harbour assembly (FICTIONAL)", "date": "c. 2064", "place": mapped["public_id"]})
    publish_new(conn, contrib, editor, "event", {"title": "Test unlocated meeting (FICTIONAL)", "date": "2066"})   # no place
    delegate = publish_new(conn, contrib, editor, "person", {"preferred_name": "Testperson Delegate (FICTIONAL)", "living_status": "deceased"})
    from tests.helpers import publish as _publish, submit_new as _submit
    _publish(conn, editor, _submit(conn, contrib, "participation", {"event": harbour["public_id"], "person": delegate["public_id"]}))
    hidden = publish_new(conn, contrib, editor, "person", {"preferred_name": "Testperson Private (FICTIONAL)", "living_status": "living"})
    conn.close()

    app = create_app({"ENV": "testing", "DATABASE_PATH": path, "SECRET_KEY": "e" * 40,
                      "MEDIA_ROOT": os.path.join(tmp, "media")})
    server = make_server("127.0.0.1", 0, app, threaded=True)
    base = f"http://127.0.0.1:{server.server_port}"
    threading.Thread(target=server.serve_forever, daemon=True).start()
    shot = (lambda page, name: page.screenshot(path=os.path.join(SHOTS, name), full_page=True)) if SHOTS else (lambda *a: None)
    steps = []

    with sync_playwright() as p:
        # WebGL for the 3D map: software rendering, so it also works on machines without a GPU
        browser = p.chromium.launch(args=["--use-angle=swiftshader", "--enable-unsafe-swiftshader"])

        # 1. Contributor drafts, then submits a person record through the real form.
        ctx = browser.new_context(viewport={"width": 1280, "height": 900})
        page = ctx.new_page()
        page.goto(base + "/")
        shot(page, "01-home.png")
        page.get_by_role("link", name="Sign in", exact=True).click()
        page.fill("#f-identifier", "e2e_contrib")
        page.fill("#f-password", PASSWORD)
        page.click("button:has-text('Sign in')")
        expect(page.locator("h1")).to_contain_text("Welcome")
        page.get_by_role("link", name="New record: Person", exact=True).click()
        page.fill("#f-preferred_name", "Testperson Browser (FICTIONAL)")
        page.fill("#f-aliases", "Testperson Brauser")
        page.fill("#f-birth", "c. 2099")
        page.fill("#f-birth_place", "Testville (FICTIONAL)")
        page.fill("#f-summary", "Synthetic person created by the browser test.")
        page.fill("#f-sources", "Test Register (FICTIONAL) | p. 9 | https://example.test/register")
        page.fill("#f-birth", "1952-02-30")                       # invalid on purpose: server must reject it
        page.click("button:has-text('Save draft')")
        expect(page.locator("#error-summary")).to_be_visible()
        expect(page.locator("#e-birth")).to_contain_text("does not exist")
        shot(page, "02-form-error.png")
        page.fill("#f-birth", "c. 2099")
        page.click("button:has-text('Save and submit for review')")
        expect(page.locator(".notice--ok")).to_contain_text("Submitted for editorial review")
        shot(page, "03-submitted.png")
        steps.append("contributor: invalid date rejected, draft saved and submitted")

        # 2. Not public yet.
        anon = browser.new_context().new_page()
        anon.goto(base + "/search?q=browser")
        expect(anon.locator("main")).to_contain_text("No published records match")
        steps.append("visitor: unpublished submission not searchable")

        # 3. Editor reviews, asks for changes.
        ectx = browser.new_context(viewport={"width": 1280, "height": 900})
        ed = ectx.new_page()
        ed.goto(base + "/auth/login")
        ed.fill("#f-identifier", "e2e_editor")
        ed.fill("#f-password", PASSWORD)
        ed.click("button:has-text('Sign in')")
        ed.goto(base + "/editor")
        shot(ed, "04-queue.png")
        ed.get_by_role("link", name="Testperson Browser (FICTIONAL)").click()
        ed.click("button:has-text('Start review')")
        ed.fill("#m-nr", "Please add an occupation if known (test).")
        ed.click("button:has-text('Return for revision')")
        expect(ed.locator(".notice--ok")).to_contain_text("Returned to the contributor")
        steps.append("editor: started review and returned it for revision")

        # 4. Contributor sees the request, revises, resubmits.
        page.goto(base + "/dashboard/submissions")
        page.get_by_role("link", name="Testperson Browser (FICTIONAL)").click()
        expect(page.locator("main")).to_contain_text("Please add an occupation")
        page.get_by_role("link", name="Edit", exact=True).click()
        expect(page.locator("#f-birth")).to_have_value("c. 2099")        # uncertainty survives the round trip
        page.fill("#f-occupation", "Test occupation (fictional)")
        page.click("button:has-text('Save and submit for review')")
        expect(page.locator(".notice--ok")).to_contain_text("Submitted")
        steps.append("contributor: saw the editor's message, revised and resubmitted")

        # 5. Editor approves and publishes.
        ed.reload()
        ed.click("button:has-text('Start review')")
        ed.click("button:has-text('Approve')")
        ed.on("dialog", lambda d: d.accept())
        shot(ed, "05-review-approved.png")
        ed.click("button:has-text('Publish')")
        expect(ed.locator(".notice--ok")).to_contain_text("Published")
        steps.append("editor: approved and published")

        # 6. Public: searchable by alias, profile shows uncertainty + citation, linked from the place page.
        anon.goto(base + "/search?q=brauser")
        anon.get_by_role("link", name="Testperson Browser (FICTIONAL)").click()
        expect(anon.locator("h1")).to_have_text("Testperson Browser (FICTIONAL)")
        expect(anon.locator("main")).to_contain_text("c. 2099")
        expect(anon.locator("main")).to_contain_text("Test Register (FICTIONAL)")
        expect(anon.locator(".notice--fictional")).to_have_count(0)       # real-flow record is not flagged as seed data
        shot(anon, "06-person.png")
        anon.get_by_role("link", name="Testville (FICTIONAL)").click()
        expect(anon.locator("main")).to_contain_text("Testperson Browser (FICTIONAL)")
        steps.append("visitor: found by alias, profile shows approximate date and citation, linked from place page")

        # 7. Mobile: compact menu works and nothing scrolls sideways.
        m = browser.new_context(viewport={"width": 375, "height": 740}, is_mobile=True, has_touch=True).new_page()
        m.goto(base + "/people")
        expect(m.locator("#nav-toggle")).to_be_visible()
        expect(m.locator("#nav-wrap")).to_be_hidden()
        m.click("#nav-toggle")
        expect(m.locator("#nav-wrap")).to_be_visible()
        expect(m.locator("#nav-toggle")).to_have_attribute("aria-expanded", "true")
        overflow = m.evaluate("document.documentElement.scrollWidth - document.documentElement.clientWidth")
        assert overflow <= 0, f"horizontal overflow of {overflow}px on mobile"
        shot(m, "07-mobile-menu.png")
        m.goto(base + "/map")
        expect(m.locator("main")).to_contain_text("Places without documented coordinates")
        steps.append("mobile: menu toggles, no horizontal overflow, map list alternative reachable")

        # 8. Keyboard: first Tab reaches the skip link and it moves focus to main.
        k = browser.new_context().new_page()
        k.goto(base + "/")
        k.keyboard.press("Tab")
        expect(k.locator(".skip")).to_be_focused()
        k.keyboard.press("Enter")
        assert k.evaluate("document.activeElement.id") == "main"
        steps.append("keyboard: skip link works")

        # 9. Languages: the switcher changes the interface; Arabic is right-to-left and fits a phone screen.
        lc = browser.new_context(viewport={"width": 1280, "height": 900})
        lp = lc.new_page()
        lp.goto(base + "/people")
        lp.get_by_role("link", name="العربية").click()
        expect(lp.locator("html")).to_have_attribute("dir", "rtl")
        expect(lp.locator("html")).to_have_attribute("lang", "ar")
        assert lp.url.endswith("/people"), lp.url                       # stayed on the same page
        expect(lp.locator("h1")).to_have_text("الأشخاص")
        expect(lp.locator(".lang-note")).to_be_visible()                 # draft-translation notice
        shot(lp, "09-arabic-people.png")
        lp.goto(base + "/")
        shot(lp, "09-arabic-home.png")
        lp.get_by_role("link", name="ትግርኛ").click()
        expect(lp.locator("html")).to_have_attribute("dir", "ltr")
        expect(lp.locator("#nav-wrap")).to_contain_text("ሰባት")
        shot(lp, "09-tigrinya-home.png")
        lm = browser.new_context(viewport={"width": 375, "height": 740}, is_mobile=True, has_touch=True).new_page()
        lm.goto(base + "/language/ar?next=/")
        lm.click("#nav-toggle")
        expect(lm.locator("#nav-wrap")).to_be_visible()
        overflow = lm.evaluate("document.documentElement.scrollWidth - document.documentElement.clientWidth")
        assert overflow <= 0, f"horizontal overflow of {overflow}px on mobile (Arabic)"
        shot(lm, "09-arabic-mobile.png")
        lp.get_by_role("link", name="English").click()
        expect(lp.locator("html")).to_have_attribute("lang", "en")
        steps.append("languages: switch to Arabic (RTL) and Tigrinya and back, no overflow on mobile in Arabic")

        # 10. Photos: contributor uploads through the real form (with progress), editor approves, visitors see it.
        img_path = os.path.join(tmp, "upload-test.jpg")
        Image.new("RGB", (1200, 800), (150, 110, 70)).save(img_path, "JPEG")
        page.goto(base + "/contribute/person")
        page.fill("#f-preferred_name", "Testperson Photo Browser (FICTIONAL)")
        page.click("button:has-text('Save draft')")
        expect(page.locator(".notice--ok")).to_contain_text("Draft saved")
        page.set_input_files("#f-photo", img_path)
        page.fill("#f-caption", "Synthetic colour block for the browser test (FICTIONAL)")
        page.select_option("#f-rights_status", "copyrighted_permission_granted")
        page.fill("#f-rights_holder", "Test Holder (FICTIONAL)")
        page.check("#f-rights_declared")
        page.click("button:has-text('Upload')")
        expect(page.locator(".notice--ok")).to_contain_text("Photo added")
        thumb = page.locator(".photo-list img").first
        expect(thumb).to_be_visible()
        # the element can be visible before its image has arrived: wait for the image itself (fails if it never loads)
        page.wait_for_function("i => i.complete && i.naturalWidth > 0", arg=thumb.element_handle(), timeout=15000)
        assert thumb.evaluate("i => i.naturalWidth") > 0
        shot(page, "10-photo-uploaded.png")
        page.click("button:has-text('Submit for review')")
        expect(page.locator(".notice--ok")).to_contain_text("Submitted")
        ed.goto(base + "/editor")
        ed.get_by_role("link", name="Testperson Photo Browser (FICTIONAL)").click()
        expect(ed.locator("main")).to_contain_text("Photo decisions needed")
        ed.click("button:has-text('Start review')")
        ed.select_option("select[name=access]", "public")
        ed.select_option("select[name=rights_status]", "copyrighted_permission_granted")
        ed.click("button:has-text('Save photo decision')")
        expect(ed.locator(".notice--ok")).to_contain_text("Photo decision saved")
        shot(ed, "10-photo-review.png")
        ed.click("button:has-text('Approve')")
        ed.click("button:has-text('Publish')")
        expect(ed.locator(".notice--ok")).to_contain_text("Published")
        anon.goto(base + "/archive")
        anon.locator(".gallery a").first.click()
        img = anon.locator("figure.photo img")
        expect(img).to_be_visible()
        anon.wait_for_function("i => i.complete && i.naturalWidth > 0", arg=img.element_handle(), timeout=15000)
        assert img.evaluate("i => i.naturalWidth") > 0
        expect(anon.locator("main")).to_contain_text("Testperson Photo Browser (FICTIONAL)")
        shot(anon, "10-archive-item.png")
        steps.append("photos: uploaded with progress, decided and published by an editor, visible to visitors")

        # 11. Explore page: the 3D map and the timeline as two perspectives on one shared, URL-backed state.
        mp = browser.new_context(viewport={"width": 1280, "height": 900}).new_page()
        external, terrain = [], []
        mp.on("request", lambda r: external.append(r.url) if not r.url.startswith(base) and not r.url.startswith(("data:", "blob:")) else None)
        mp.on("request", lambda r: terrain.append(r.url) if "/static/map/terrain/" in r.url else None)
        mp.goto(base + "/map")
        expect(mp.locator(".atlas-view.is-live")).to_be_visible(timeout=60000)
        expect(mp.locator(".atlas-map canvas")).to_have_attribute("role", "region")
        expect(mp.locator(".atlas-pin")).to_have_count(1, timeout=30000)
        expect(mp.locator(".atlas-pin")).to_have_attribute("aria-label", "Testhaven (FICTIONAL) — Other historically relevant place — Approximate")
        expect(mp.locator("#tl-scope")).to_be_hidden()                                 # map mode: the map is the focus
        mp.wait_for_load_state("networkidle")
        assert terrain, "no terrain tiles were requested"
        # (1) a town on the map → its documented events on the timeline, place filter shown and removable
        mp.locator(".atlas-result", has_text="Testhaven").click()
        expect(mp.locator("#atlas-detail h2")).to_have_text("Testhaven (FICTIONAL)")
        expect(mp.locator("#atlas-detail")).to_contain_text("Test harbour assembly (FICTIONAL)")
        mp.locator("#atlas-detail button", has_text="Explore this place on the timeline").click()
        expect(mp.locator("#tl-scope")).to_be_visible()
        expect(mp.locator(".atlas-mode[aria-current=page]")).to_have_text("Timeline")
        expect(mp.locator(".atlas-chip", has_text="Events at: Testhaven")).to_be_visible()
        expect(mp.locator("#ex-context h2")).to_have_text("Testhaven (FICTIONAL)")
        expect(mp.locator(".tl-ev")).to_have_count(1)                                   # only the event documented AT Testhaven
        assert "at=" in mp.url and "mode=timeline" in mp.url, mp.url
        mp.locator(".atlas-chip", has_text="Events at").click()
        expect(mp.locator(".tl-ev")).to_have_count(2)
        # (2) an event on the timeline → its location on the map, with its record preview
        mp.locator(".tl-ev[aria-label^='Test harbour']").click()
        expect(mp.locator("#tl-card h3")).to_have_text("Test harbour assembly (FICTIONAL)")
        expect(mp.locator("#tl-card")).to_contain_text("Somewhere within this span")
        mp.locator("#tl-card .atlas-links button", has_text="Show on the map").click()
        expect(mp.locator(".atlas-mode[aria-current=page]")).to_have_text("Map")
        expect(mp.locator("#atlas-detail h2")).to_have_text("Testhaven (FICTIONAL)", timeout=30000)   # its one documented place
        expect(mp.locator(".atlas-back")).to_contain_text("Back to Test harbour assembly")
        expect(mp.locator(".atlas-pin.is-selected")).to_have_count(1)
        assert "event=" in mp.url and "place=" in mp.url, mp.url
        mp.locator(".atlas-back").click()
        expect(mp.locator("#atlas-detail h2")).to_have_text("Test harbour assembly (FICTIONAL)")
        # (4) a person profile from the event preview, then (5) back to the same exploration context
        mp.locator("#atlas-detail a", has_text="Testperson Delegate").click()
        expect(mp.locator("h1")).to_have_text("Testperson Delegate (FICTIONAL)")
        mp.go_back()
        expect(mp.locator("#atlas-detail h2")).to_have_text("Test harbour assembly (FICTIONAL)", timeout=60000)
        mp.go_back()                                                                     # one step further: the place panel
        expect(mp.locator("#atlas-detail h2")).to_have_text("Testhaven (FICTIONAL)", timeout=60000)
        mp.go_forward()
        expect(mp.locator("#atlas-detail h2")).to_have_text("Test harbour assembly (FICTIONAL)")
        # (3) the period, changed on the timeline, applies to the map too (and back)
        mp.click(".atlas-mode--both")
        expect(mp.locator("#tl-scope")).to_be_visible(); expect(mp.locator("#atlas")).to_be_visible()
        mp.locator("#ex-from").fill("2065"); mp.locator("#ex-from").press("Tab")
        expect(mp.locator("#ribbon-range")).to_have_text("2065 – …")
        expect(mp.locator(".atlas-pin")).to_have_count(0)                               # c. 2064 is outside the period
        expect(mp.locator(".tl-ev")).to_have_count(1)                                   # the 2066 meeting
        expect(mp.locator("#tl-count")).to_contain_text("no longer selected")            # the deselection is explained
        mp.locator(".atlas-chip", has_text="Period").click()
        expect(mp.locator(".atlas-pin")).to_have_count(1)
        expect(mp.locator(".tl-ev")).to_have_count(2)
        # (7) an event without a documented location: no marker, and the reason is given
        mp.locator(".tl-ev[aria-label^='Test unlocated']").click()
        expect(mp.locator("#tl-card")).to_contain_text("has not been established")
        expect(mp.locator("#tl-card .atlas-links button", has_text="Show on the map")).to_have_count(0)
        expect(mp.locator("#atlas-detail")).to_contain_text("No place with documented coordinates", timeout=30000)
        expect(mp.locator(".atlas-pin")).to_have_count(1)                               # still only Testhaven; nothing invented
        expect(mp.locator(".atlas-pin.is-related, .atlas-pin.is-selected")).to_have_count(0)
        shot(mp, "11-explore-both.png")
        # (6) share the address: a new visitor gets the same public selection
        shared = mp.url
        sp = browser.new_context(viewport={"width": 1280, "height": 900}).new_page()
        sp.goto(shared)
        expect(sp.locator("#tl-card h3")).to_have_text("Test unlocated meeting (FICTIONAL)", timeout=60000)
        expect(sp.locator(".atlas-mode[aria-current=page]")).to_have_text("Map and timeline")
        # (9) clear filters → no selection, the national overview
        mp.locator("#ex-from").fill("2060"); mp.locator("#ex-from").press("Tab")
        expect(mp.locator(".atlas-chip")).to_have_count(1)
        mp.click("#ex-clear")
        expect(mp.locator("#ex-chips")).to_be_hidden()
        expect(mp.locator("#tl-card")).to_be_hidden()
        expect(mp.locator("#atlas-detail")).to_be_hidden()
        assert "from=" not in mp.url and "event=" not in mp.url, mp.url
        expect(mp.locator(".atlas-pin")).to_have_count(1)
        expect(mp.locator("main")).to_contain_text("Places without documented coordinates")
        assert not external, f"the atlas made requests to other sites: {external[:3]}"
        # (10) private or unpublished records never enter the shared state
        pv = browser.new_context(viewport={"width": 1280, "height": 900}).new_page()
        pv.goto(base + f"/explore?person={hidden['public_id']}&event={hidden['public_id']}&record={hidden['public_id']}")
        expect(pv.locator(".notice")).to_contain_text("not public or no longer exists")
        assert "Testperson Private" not in pv.content()
        expect(pv.locator(".atlas-chip")).to_have_count(0)
        assert hidden["public_id"] not in pv.url, pv.url
        # search across record types still works on the shared page
        mp.fill("#ex-q", "harbour")
        expect(mp.locator("#atlas-found-list .atlas-result").first).to_contain_text("Event", timeout=30000)
        mp.fill("#ex-q", "")
        # (8) phone: no split view; map first, bottom sheet, timeline one tap away
        ph = browser.new_context(viewport={"width": 390, "height": 844}, is_mobile=True, has_touch=True).new_page()
        ph.goto(base + "/explore")
        expect(ph.locator(".atlas-mode[aria-current=page]")).to_have_text("Map")          # the split view is not used on phones
        expect(ph.locator(".atlas-mode--both")).to_be_hidden()
        expect(ph.locator(".atlas-view.is-live")).to_be_visible(timeout=60000)
        ph.locator(".atlas-pin").first.tap()
        expect(ph.locator("#atlas-detail h2")).to_have_text("Testhaven (FICTIONAL)")
        assert ph.evaluate("getComputedStyle(document.getElementById(\"atlas-detail\")).position") == "fixed"
        ph.locator(".atlas-back").tap()
        ph.locator(".atlas-mode--timeline").tap()
        expect(ph.locator(".tl-ev")).to_have_count(2)
        ph.locator(".tl-ev").first.tap()
        expect(ph.locator("#tl-card h3")).to_be_visible()
        assert ph.evaluate("document.documentElement.scrollWidth - document.documentElement.clientWidth") <= 0
        shot(ph, "11-explore-phone.png")
        # fallbacks: no WebGL, and no elevation data
        nw = browser.new_context(viewport={"width": 1280, "height": 900}).new_page()
        nw.add_init_script("HTMLCanvasElement.prototype.getContext = function () { return null; };")
        nw.goto(base + "/map")
        expect(nw.locator(".atlas-flat .atlas-pin")).to_have_count(1, timeout=30000)
        expect(nw.locator("#atlas-toast")).to_contain_text("simplified flat map")
        nw.locator(".atlas-flat .atlas-pin").click()
        expect(nw.locator("#atlas-detail h2")).to_have_text("Testhaven (FICTIONAL)")
        nd = browser.new_context(viewport={"width": 1280, "height": 900}).new_page()
        nd.route("**/static/map/terrain/**", lambda route: route.fulfill(status=404, body=""))
        nd.goto(base + "/map")
        expect(nd.locator("#atlas-toast")).to_contain_text("Elevation data could not be loaded", timeout=60000)
        expect(nd.locator("[data-act=terrain]")).to_be_disabled()
        # keyboard only, with reduced motion: open a place from the list and an event on the timeline, close with
        # Escape, and focus returns to what opened them; the panels appear without animation
        kb = browser.new_context(viewport={"width": 1280, "height": 900}, reduced_motion="reduce").new_page()
        kb.goto(base + "/explore?mode=both")
        expect(kb.locator(".atlas-view.is-live")).to_be_visible(timeout=60000)
        expect(kb.locator(".tl-ev")).to_have_count(2, timeout=30000)
        kb.locator(".atlas-result", has_text="Testhaven").focus()
        kb.keyboard.press("Enter")
        expect(kb.locator("#atlas-detail h2")).to_be_focused()
        assert kb.evaluate("getComputedStyle(document.getElementById('atlas-detail')).animationName") == "none"
        kb.keyboard.press("Escape")
        expect(kb.locator("#atlas-detail")).to_be_hidden()
        assert kb.evaluate("document.activeElement.textContent").find("Testhaven") >= 0
        kb.locator(".tl-ev[aria-label^='Test harbour']").focus()
        kb.keyboard.press("Enter")
        expect(kb.locator("#tl-card h3")).to_have_text("Test harbour assembly (FICTIONAL)")
        assert kb.evaluate("getComputedStyle(document.getElementById('tl-card')).animationName") == "none"
        kb.keyboard.press("Escape")
        expect(kb.locator("#tl-card")).to_be_hidden()
        assert (kb.evaluate("document.activeElement.getAttribute('aria-label') || ''")).startswith("Test harbour")
        steps.append("atlas keyboard and reduced motion: list → panel → Escape returns focus; no panel animation")

        # 11b. Choosing locations on a map in the forms, and the atlas's editorial depth.
        page.goto(base + "/contribute/place")
        expect(page.locator(".locpick.is-live")).to_be_visible(timeout=60000)
        page.wait_for_load_state("networkidle")
        page.locator(".locpick__map").scroll_into_view_if_needed()
        mb = page.locator(".locpick__map").bounding_box()
        page.mouse.click(mb["x"] + mb["width"] * 0.5, mb["y"] + mb["height"] * 0.5)
        expect(page.locator("#f-latitude")).not_to_have_value("")
        expect(page.locator(".locpick__status")).to_contain_text("choose the coordinate precision")
        lat = float(page.input_value("#f-latitude")); lon = float(page.input_value("#f-longitude"))
        assert 9 < lat < 22 and 31 < lon < 48, (lat, lon)                       # a point on the map shown, nothing invented
        page.fill("#f-primary_name", "Testpicked (FICTIONAL)")
        page.click("button:has-text('Save and submit for review')")
        expect(page.locator("#e-coord_precision")).to_be_visible()              # the contributor must still state the precision
        page.select_option("#f-coord_precision", "approximate")
        page.click("button:has-text('Save and submit for review')")
        expect(page.locator(".notice--ok")).to_contain_text("Submitted for editorial review")
        shot(page, "11b-picker-place.png")
        page.goto(base + "/contribute/event")
        page.click("button:has-text('Choose on the map')")
        expect(page.locator(".locpick__place")).to_have_count(1, timeout=60000)
        page.locator(".locpick__place").click()
        expect(page.locator("#f-place")).to_have_value(f"Testhaven (FICTIONAL) [{mapped['public_id']}]")
        expect(page.locator(".locpick__status")).to_contain_text("approximate")
        # reviewers see the proposal on the map; visitors never do
        ed.goto(base + "/map")
        expect(ed.locator(".atlas-view.is-live")).to_be_visible(timeout=60000)
        ed.click("[data-act=layers]")
        ed.check("[data-layer=proposals]")
        expect(ed.locator(".atlas-proposal")).to_have_count(1, timeout=30000)
        expect(ed.locator(".atlas-proposal")).to_have_attribute("aria-label", "Proposed: Testpicked (FICTIONAL) — Awaiting review (visible to editors only)")
        ed.uncheck("[data-layer=evplaces]")
        expect(ed.locator(".atlas-pin")).to_have_count(0)                         # Testhaven has events
        ed.check("[data-layer=evplaces]")
        expect(ed.locator(".atlas-pin")).to_have_count(1)
        assert "Testpicked" not in mp.request.get(base + "/map/data.json").text()
        # a period: a short summary from the records, then the shortcuts in the place panel
        dp = browser.new_context(viewport={"width": 1280, "height": 900}).new_page()
        dp.goto(base + "/explore?mode=both&from=2060&to=2069")
        expect(dp.locator("#ex-pctx")).to_be_visible(timeout=30000)
        expect(dp.locator("#ex-pctx")).to_contain_text("2 dated events")
        expect(dp.locator("#ex-pctx")).to_contain_text("1 of them with an approximate or decade-only date")
        dp.locator("#ex-pctx summary").click()
        expect(dp.locator("#ex-pctx")).to_contain_text("Testhaven (FICTIONAL)")
        dp.locator("#ex-pctx button", has_text="Show this place on the map").click()
        expect(dp.locator("#atlas-detail h2")).to_have_text("Testhaven (FICTIONAL)", timeout=30000)
        expect(dp.locator("#atlas-detail a", has_text="Explore this place's history")).to_have_attribute("href", f"/places/{mapped['slug']}")
        expect(dp.locator("#atlas-detail button", has_text="Copy a link to this view")).to_be_visible()
        shot(dp, "11b-period-context.png")
        # a curated exploration: saved by an editor, shown with its editor and sources
        ed.goto(base + "/editor/explorations")
        ed.fill("#xt", "Test harbour exploration (FICTIONAL)")
        ed.fill("#xd", "A fictional selection used only by the browser test.")
        ed.fill("#xs", "Test Harbour Register (FICTIONAL)")
        ed.fill("#xf", "2060"); ed.fill("#xo", "2069")
        ed.fill("#f-items", f"Testhaven (FICTIONAL) [{mapped['public_id']}]\nTest harbour assembly [{harbour['public_id']}] | The fictional assembly.")
        ed.check("#xp")
        ed.click("button:has-text('Save exploration')")
        expect(ed.locator(".notice--ok")).to_contain_text("Exploration saved")
        anon.goto(base + "/explore/curated")
        anon.get_by_role("link", name="Test harbour exploration (FICTIONAL)").click()
        expect(anon.locator("main")).to_contain_text("Curated by E2E_Editor")
        expect(anon.locator("main")).to_contain_text("The fictional assembly.")
        expect(anon.locator("main")).to_contain_text("Test Harbour Register (FICTIONAL)")
        anon.get_by_role("link", name="Open this period in the atlas").click()
        expect(anon.locator("#ex-pctx")).to_contain_text("2 dated events", timeout=30000)
        curated_url = anon.url
        shot(anon, "11b-curated.png")
        steps.append("atlas depth: location chosen on a map (precision still required), place chosen on a map for an event, "
                     "reviewers' proposal layer, place layers, period summary, place shortcuts, curated exploration")
        steps.append("explore: map ↔ timeline through one shared, URL-backed state — place → its events, event → its location, "
                     "shared period, person profile and back/forward, shared link, unlocated event, phone, clear, private records excluded")

        # 12. Forum: a member posts, another replies and reports it, a moderator removes it with a reason.
        page.goto(base + "/community/c/hometowns/new")
        page.fill("#tt", "Browser test topic (FICTIONAL)")
        page.fill("#tb", "A synthetic forum post written by the browser test (FICTIONAL).")
        page.click("button:has-text('Post topic')")
        expect(page.locator("h1")).to_have_text("Browser test topic (FICTIONAL)")
        topic_url = page.url
        ed.goto(topic_url)
        ed.fill("#rb", "A synthetic reply (FICTIONAL).")
        ed.click("button:has-text('Post reply')")
        expect(ed.locator("main")).to_contain_text("A synthetic reply (FICTIONAL).")
        ed.locator("details.inline-details summary", has_text="Report").first.click()
        ed.locator("button:has-text('Send report')").first.click()
        expect(ed.locator(".notice--ok")).to_contain_text("A moderator will look at your report")
        mod = browser.new_context(viewport={"width": 1280, "height": 900}).new_page()
        mod.goto(base + "/auth/login")
        mod.fill("#f-identifier", "e2e_mod")
        mod.fill("#f-password", PASSWORD)
        mod.click("button:has-text('Sign in')")
        mod.goto(base + "/moderation")
        expect(mod.locator("main")).to_contain_text("Browser test topic (FICTIONAL)")
        shot(mod, "12-moderation-queue.png")
        mod.goto(topic_url)
        mod.locator("details.inline-details summary", has_text="Moderate").first.click()
        first_post = mod.locator("form[action^='/moderation/posts/']").first
        first_post.locator("select[name=action]").select_option("remove")
        first_post.locator("input[name=reason]").fill("Browser test of moderation (FICTIONAL)")
        first_post.locator("button:has-text('Apply')").click()
        expect(mod.locator(".notice--ok")).to_contain_text("moderation log")
        anon.goto(topic_url)
        expect(anon.locator("main")).to_contain_text("This post was removed by a moderator.")
        expect(anon.locator("main")).not_to_contain_text("written by the browser test")
        steps.append("forum: posted, replied, reported, removed by a moderator with a logged reason")

        # 13. Merge: an editor merges a duplicate; the retired record's address redirects to the kept one.
        ed.goto(base + f"/editor/merge?keep={dup_keep['public_id']}&retire={dup_retire['public_id']}")
        expect(ed.locator("main")).to_contain_text("Testperson Twin (FICTIONAL)")
        ed.fill("#mr", "Same person: identical test records created by the browser test (FICTIONAL).")
        ed.click("button:has-text('Merge')")
        expect(ed.locator(".notice--ok")).to_contain_text("now redirects")
        anon.goto(base + f"/people/{dup_retire['slug']}")
        assert anon.url.endswith(f"/people/{dup_keep['slug']}"), anon.url
        steps.append("merge: duplicate merged with a reason; old address redirects")

        # 14. Accessibility: axe-core (WCAG 2.0–2.2 A/AA rules) on the main pages, public and signed in, English and Arabic.
        axe = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "vendor", "axe.min.js"), encoding="utf-8").read()
        person_slug = dup_keep["slug"]
        public_pages = ["/", "/people", f"/people/{person_slug}", f"/places/{place['slug']}", f"/places/{mapped['slug']}", "/map", "/timeline", "/families",
                        "/archive", "/oral-histories", "/community", f"/map?place={mapped['public_id']}", f"/timeline?place={mapped['public_id']}", "/explore", topic_url.replace(base, ""), "/search?q=test", "/about",
                        "/standards", "/contact", "/auth/login", "/auth/register", "/accessibility", "/explore/curated",
                        "/explore/curated/test-harbour-exploration-fictional", "/explore?mode=both&from=2060&to=2069"]
        assert curated_url
        problems = []

        def scan(pg, url):
            pg.goto(base + url)
            pg.wait_for_load_state("networkidle"); pg.wait_for_timeout(700)      # let fade-ins finish (mid-animation text is faint)
            pg.add_script_tag(content=axe)
            res = pg.evaluate("""() => axe.run(document, {runOnly: {type: 'tag', values: ['wcag2a','wcag2aa','wcag21a','wcag21aa','wcag22aa']}})
                                  .then(r => r.violations.map(v => ({id: v.id, impact: v.impact, n: v.nodes.length,
                                                                    target: v.nodes.slice(0, 4).map(function (n) { return n.target.join(' ') + ' {' + (n.failureSummary || '').slice(0, 160) + '}'; }).join(' | '), help: v.help})))""")
            for v in res:
                problems.append(f"{url} [{v['impact']}] {v['id']}: {v['help']} ({v['n']}x, e.g. {v['target']})")

        actx = browser.new_context(viewport={"width": 1280, "height": 900}, bypass_csp=True)   # CSP bypass only to inject axe
        ap = actx.new_page()
        for u in public_pages:
            scan(ap, u)
        ap.goto(base + "/language/ar?next=/")
        for u in ("/", "/people", f"/people/{person_slug}", "/contact"):
            scan(ap, u)
        ap.goto(base + "/language/en?next=/")
        ap.goto(base + "/auth/login")
        ap.fill("#f-identifier", "e2e_editor")
        ap.fill("#f-password", PASSWORD)
        ap.click("button:has-text('Sign in')")
        signed_in = ("/dashboard", "/dashboard/profile", "/dashboard/security", "/contribute/person", "/contribute/place", "/editor",
                     "/editor/duplicates", "/editor/explorations")
        for u in signed_in:
            scan(ap, u)
        dark = browser.new_context(viewport={"width": 1280, "height": 900}, bypass_csp=True, color_scheme="dark").new_page()
        dark_pages = ("/", "/people", f"/people/{person_slug}", "/map", topic_url.replace(base, ""), "/archive", "/auth/login")
        for u in dark_pages:
            scan(dark, u)
        n_pages = len(public_pages) + 4 + len(signed_in) + len(dark_pages)
        if problems:
            print("\n".join(problems))
            raise AssertionError(f"{len(problems)} accessibility violation(s) found by axe-core")
        steps.append(f"accessibility: axe-core found no WCAG A/AA violations on {n_pages} pages (English, Arabic, signed in, dark mode)")

        browser.close()
    server.shutdown()
    for s in steps:
        print("PASS", s)
    print(f"{len(steps)} browser scenarios passed")


if __name__ == "__main__":
    main()
