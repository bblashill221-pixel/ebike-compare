"""Shared warranty extractor for the e-bike scrapers.

`JS_WARRANTY` is a Playwright page.evaluate() body that scans the rendered page
text for a warranty statement (e.g. "2-Year Warranty", "Lifetime Warranty") and
returns the most common normalized phrase, or null if none is found.
"""

JS_WARRANTY = r"""() => {
    const txt = document.body.innerText || '';
    const re = /(\d+)[\s-]?year[s]?(?:[\s-]?limited)?[\s-]?warranty|lifetime[\s-]?warranty/gi;
    const counts = {};
    let m;
    while ((m = re.exec(txt))) {
        let phrase = m[0].toLowerCase().replace(/\s+/g, ' ').trim()
            .replace(/(\d+)[\s-]?years?/, '$1-year');
        counts[phrase] = (counts[phrase] || 0) + 1;
    }
    let best = null, bc = 0;
    for (const k in counts) if (counts[k] > bc) { bc = counts[k]; best = k; }
    // Title-case for readability: "2-year warranty" -> "2-Year Warranty".
    return best ? best.replace(/\b\w/g, c => c.toUpperCase()) : null;
}"""
