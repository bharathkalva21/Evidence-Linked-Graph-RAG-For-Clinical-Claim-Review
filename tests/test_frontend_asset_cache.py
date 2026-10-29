"""The report page must not reuse a script or stylesheet from an older layout."""

import asyncio

import httpx

from backend.main import app


def test_ui_assets_are_versioned_and_not_cached():
    async def inspect():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            page = await client.get("/ui/")
            script = await client.get("/ui/app.js?v=claim-step-7-ui-fix-1")
            style = await client.get("/ui/style.css?v=claim-step-7-ui-fix-1")
            return page, script, style

    page, script, style = asyncio.run(inspect())
    assert all(response.status_code == 200 for response in (page, script, style))
    assert all(response.headers["cache-control"] == "no-store, max-age=0"
               for response in (page, script, style))
    assert 'src="app.js?v=claim-step-7-ui-fix-1"' in page.text
    assert 'href="style.css?v=claim-step-7-ui-fix-1"' in page.text
    assert "The analysis finished, but this page could not display the report" in script.text
    assert ".review-section" in style.text
