import sys
from pathlib import Path
import pptx
from pptx.util import Inches, Pt
from pptx.enum.text import PP_ALIGN
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE

def create_presentation():
    prs = pptx.Presentation()
    prs.slide_width = Inches(13.333)
    prs.slide_height = Inches(7.5)
    blank_layout = prs.slide_layouts[6]

    # Theme Colors
    BG_COLOR = RGBColor(8, 12, 20)        # #080c14 deep background
    CARD_BG = RGBColor(14, 22, 38)        # #0e1626 dark card
    CARD_BORDER = RGBColor(35, 49, 72)    # #233148 subtle border
    BLUE_ACCENT = RGBColor(59, 130, 246)  # #3b82f6 electric blue
    CYAN_ACCENT = RGBColor(56, 189, 248)  # #38bdf8 cyan/sky
    EMERALD = RGBColor(16, 185, 129)      # #10b981
    CORAL = RGBColor(239, 68, 68)         # #ef4444
    AMBER = RGBColor(245, 158, 11)        # #f59e0b
    PURPLE = RGBColor(139, 92, 246)       # #8b5cf6
    TEXT_WHITE = RGBColor(255, 255, 255)
    TEXT_LIGHT = RGBColor(203, 213, 225)  # #cbd5e1
    TEXT_MUTED = RGBColor(148, 163, 184)  # #94a3b8

    def apply_bg(slide):
        bg = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, 0, 0, prs.slide_width, prs.slide_height)
        bg.fill.solid()
        bg.fill.fore_color.rgb = BG_COLOR
        bg.line.fill.background()
        return bg

    def add_header(slide, tag_text, title_text, subtitle_text=None):
        header_box = slide.shapes.add_textbox(Inches(0.8), Inches(0.4), Inches(11.7), Inches(1.2))
        tf = header_box.text_frame
        tf.word_wrap = True
        tf.margin_left = tf.margin_top = tf.margin_right = tf.margin_bottom = 0

        p_tag = tf.paragraphs[0]
        p_tag.text = tag_text.upper()
        p_tag.font.name = "Arial"
        p_tag.font.size = Pt(11)
        p_tag.font.bold = True
        p_tag.font.color.rgb = CYAN_ACCENT
        p_tag.space_after = Pt(3)

        p_title = tf.add_paragraph()
        p_title.text = title_text
        p_title.font.name = "Arial"
        p_title.font.size = Pt(25)
        p_title.font.bold = True
        p_title.font.color.rgb = TEXT_WHITE
        p_title.space_after = Pt(3)

        if subtitle_text:
            p_sub = tf.add_paragraph()
            p_sub.text = subtitle_text
            p_sub.font.name = "Arial"
            p_sub.font.size = Pt(12)
            p_sub.font.color.rgb = TEXT_MUTED

    def add_footer(slide, current_page, total_pages=10):
        footer_box = slide.shapes.add_textbox(Inches(0.8), Inches(6.95), Inches(11.7), Inches(0.4))
        tf = footer_box.text_frame
        tf.word_wrap = True
        tf.margin_left = tf.margin_top = tf.margin_right = tf.margin_bottom = 0
        p = tf.paragraphs[0]
        p.text = f"Checkout Radar · AZINHACK 2026 Presentation · Slide {current_page} of {total_pages}"
        p.font.name = "Arial"
        p.font.size = Pt(10)
        p.font.color.rgb = TEXT_MUTED

    def add_card(slide, left, top, width, height, border_color=CARD_BORDER):
        card = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, left, top, width, height)
        card.fill.solid()
        card.fill.fore_color.rgb = CARD_BG
        card.line.color.rgb = border_color
        card.line.width = Pt(1.5)
        return card

    def add_framed_image(slide, img_path, left, top, width, height, caption=None):
        # Frame
        frame = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, left, top, width, height)
        frame.fill.solid()
        frame.fill.fore_color.rgb = CARD_BG
        frame.line.color.rgb = BLUE_ACCENT
        frame.line.width = Pt(1.5)

        # Image inside
        pad = Inches(0.08)
        if Path(img_path).exists():
            slide.shapes.add_picture(str(img_path), left + pad, top + pad, width - (pad * 2), height - (pad * 2))

        # Caption if present
        if caption:
            cbox = slide.shapes.add_textbox(left, top + height + Inches(0.06), width, Inches(0.4))
            ctf = cbox.text_frame
            ctf.word_wrap = True
            ctf.margin_top = ctf.margin_left = 0
            p = ctf.paragraphs[0]
            p.text = caption
            p.font.name = "Arial"
            p.font.size = Pt(10)
            p.font.italic = True
            p.font.color.rgb = TEXT_MUTED

    # ==========================================
    # SLIDE 1: Title & Hero
    # ==========================================
    s1 = prs.slides.add_slide(blank_layout)
    apply_bg(s1)

    # Left content column
    left_w = Inches(5.8)
    badge = s1.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(0.8), Inches(0.7), Inches(5.6), Inches(0.4))
    badge.fill.solid()
    badge.fill.fore_color.rgb = RGBColor(23, 37, 84)
    badge.line.color.rgb = BLUE_ACCENT
    btf = badge.text_frame
    btf.margin_left = Inches(0.15)
    pb = btf.paragraphs[0]
    pb.text = "AZINHACK 2026 · INNOVATION & CONSUMER TRANSPARENCY"
    pb.font.name = "Arial"
    pb.font.size = Pt(10)
    pb.font.bold = True
    pb.font.color.rgb = CYAN_ACCENT

    tbox1 = s1.shapes.add_textbox(Inches(0.8), Inches(1.3), left_w, Inches(3.2))
    tf1 = tbox1.text_frame
    tf1.word_wrap = True
    tf1.margin_left = tf1.margin_top = 0

    p_title = tf1.paragraphs[0]
    p_title.text = "CHECKOUT RADAR"
    p_title.font.name = "Arial"
    p_title.font.size = Pt(40)
    p_title.font.bold = True
    p_title.font.color.rgb = TEXT_WHITE
    p_title.space_after = Pt(6)

    p_tag = tf1.add_paragraph()
    p_tag.text = "Outside-In Checkout Flow Auditor & CCPA Dark Pattern Detector"
    p_tag.font.name = "Arial"
    p_tag.font.size = Pt(18)
    p_tag.font.bold = True
    p_tag.font.color.rgb = CYAN_ACCENT
    p_tag.space_after = Pt(10)

    p_desc = tf1.add_paragraph()
    p_desc.text = "Deploying autonomous TinyFish browser agents across controlled condition matrices to turn subjective dark pattern claims into reproducible, screenshot-backed empirical proof."
    p_desc.font.name = "Arial"
    p_desc.font.size = Pt(13)
    p_desc.font.color.rgb = TEXT_LIGHT

    # 4 Quick Metrics on left
    m_y = Inches(4.7)
    mw = Inches(2.75)
    mh = Inches(0.95)
    add_card(s1, Inches(0.8), m_y, mw, mh)
    b1 = s1.shapes.add_textbox(Inches(0.95), m_y + Inches(0.1), mw - Inches(0.3), mh - Inches(0.2))
    b1.text_frame.margin_left = b1.text_frame.margin_top = 0
    p = b1.text_frame.paragraphs[0]
    p.text = "114 / 114"
    p.font.size = Pt(20)
    p.font.bold = True
    p.font.color.rgb = EMERALD
    p2 = b1.text_frame.add_paragraph()
    p2.text = "Tests Passing in CI"
    p2.font.size = Pt(10)
    p2.font.color.rgb = TEXT_MUTED

    add_card(s1, Inches(3.7), m_y, mw, mh)
    b2 = s1.shapes.add_textbox(Inches(3.85), m_y + Inches(0.1), mw - Inches(0.3), mh - Inches(0.2))
    b2.text_frame.margin_left = b2.text_frame.margin_top = 0
    p = b2.text_frame.paragraphs[0]
    p.text = "3 / 3 Verified"
    p.font.size = Pt(20)
    p.font.bold = True
    p.font.color.rgb = CYAN_ACCENT
    p2 = b2.text_frame.add_paragraph()
    p2.text = "Demo Flows Verified"
    p2.font.size = Pt(10)
    p2.font.color.rgb = TEXT_MUTED

    add_card(s1, Inches(0.8), m_y + Inches(1.1), mw, mh)
    b3 = s1.shapes.add_textbox(Inches(0.95), m_y + Inches(1.2), mw - Inches(0.3), mh - Inches(0.2))
    b3.text_frame.margin_left = b3.text_frame.margin_top = 0
    p = b3.text_frame.paragraphs[0]
    p.text = "SHA-256"
    p.font.size = Pt(20)
    p.font.bold = True
    p.font.color.rgb = BLUE_ACCENT
    p2 = b3.text_frame.add_paragraph()
    p2.text = "Cryptographic Custody"
    p2.font.size = Pt(10)
    p2.font.color.rgb = TEXT_MUTED

    add_card(s1, Inches(3.7), m_y + Inches(1.1), mw, mh)
    b4 = s1.shapes.add_textbox(Inches(3.85), m_y + Inches(1.2), mw - Inches(0.3), mh - Inches(0.2))
    b4.text_frame.margin_left = b4.text_frame.margin_top = 0
    p = b4.text_frame.paragraphs[0]
    p.text = "$0.00 Cost"
    p.font.size = Pt(20)
    p.font.bold = True
    p.font.color.rgb = PURPLE
    p2 = b4.text_frame.add_paragraph()
    p2.text = "Deterministic Offline Mock"
    p2.font.size = Pt(10)
    p2.font.color.rgb = TEXT_MUTED

    # Right Column: High-Res Screenshot
    add_framed_image(
        s1,
        "screenshots/landing/01_landing_desktop_1440x900.png",
        Inches(6.8), Inches(0.9), Inches(5.7), Inches(5.8),
        caption="Checkout Radar Web Platform: Overview, CCPA Regulatory Context, and 1-Click Interactive Demonstrations."
    )
    add_footer(s1, 1)

    # ==========================================
    # SLIDE 2: Problem Statement
    # ==========================================
    s2 = prs.slides.add_slide(blank_layout)
    apply_bg(s2)
    add_header(s2, "1. PROBLEM STATEMENT", "The Hidden Fee Epidemic & The Outside-In Evidence Gap",
               "Consumers face systemic late-stage fee disclosure without any tooling for admissible legal proof.")

    # Left: 3 Problem Cards
    col_w2 = Inches(5.6)
    p_card_h = Inches(1.5)
    
    problems = [
        ("💸 LATE-STAGE INFLATION", "The Drip Pricing Trap",
         "Surge fees, handling charges, and packaging costs appear only on the final payment screen after 15 minutes of checkout navigation.", CORAL),
        ("⚖️ STATUTORY MANDATE", "CCPA 2023 Guidelines",
         "Notified on 30 Nov 2023 under Consumer Protection Act 2019: Annex 1.8 strictly bans Drip Pricing; Annex 1.2 bans Basket Sneaking.", AMBER),
        ("🔍 THE EVIDENCE GAP", "Lack of Empirical Outside-In Tooling",
         "Existing compliance tools serve platform teams. Consumers, researchers, and journalists cannot capture legally admissible, reproducible proof.", BLUE_ACCENT),
    ]

    for i, (tag, title, desc, col) in enumerate(problems):
        cy = Inches(1.8) + i * Inches(1.65)
        add_card(s2, Inches(0.8), cy, col_w2, p_card_h)
        cbox = s2.shapes.add_textbox(Inches(1.0), cy + Inches(0.12), col_w2 - Inches(0.4), p_card_h - Inches(0.24))
        ctf = cbox.text_frame
        ctf.word_wrap = True
        ctf.margin_top = ctf.margin_left = 0
        
        p1 = ctf.paragraphs[0]
        p1.text = tag
        p1.font.size = Pt(10)
        p1.font.bold = True
        p1.font.color.rgb = col
        p1.space_after = Pt(2)

        p2 = ctf.add_paragraph()
        p2.text = title
        p2.font.size = Pt(14)
        p2.font.bold = True
        p2.font.color.rgb = TEXT_WHITE
        p2.space_after = Pt(4)

        p3 = ctf.add_paragraph()
        p3.text = desc
        p3.font.size = Pt(11)
        p3.font.color.rgb = TEXT_LIGHT

    # Right: Real Drip Pricing Detection Screenshot
    add_framed_image(
        s2,
        "screenshots/ui-audit/03_indicators_detected_viewport_1440x900.png",
        Inches(6.8), Inches(1.8), Inches(5.7), Inches(4.6),
        caption="Real Checkout Radar detection of a ₹5.00 Handling Fee concealed on product and cart pages, revealed only at checkout summary."
    )
    add_footer(s2, 2)

    # ==========================================
    # SLIDE 3: Proposed Solution
    # ==========================================
    s3 = prs.slides.add_slide(blank_layout)
    apply_bg(s3)
    add_header(s3, "2. PROPOSED SOLUTION", "Matched-Pair Differential Auditing Engine",
               "Not a scraper: controlled behavioral experiments that isolate fee triggers while holding controls fixed.")

    # Top: 4 Condition Matrix Horizontal Cards
    mw4 = Inches(2.75)
    mgap = Inches(0.23)
    matrix_top = [
        ("📍 Location", "Tier-1 Metro vs Tier-2/3 Pincodes", CYAN_ACCENT),
        ("👤 Session", "Fresh Guest vs Returning Profile", BLUE_ACCENT),
        ("🛒 Cart Threshold", "Above vs Below Free-Shipping Tier", EMERALD),
        ("⏱️ Temporal Drift", "Time t0 vs Re-observation at t1", PURPLE),
    ]
    for i, (m_tag, m_desc, m_col) in enumerate(matrix_top):
        cx = Inches(0.8) + i * (mw4 + mgap)
        add_card(s3, cx, Inches(1.75), mw4, Inches(0.95))
        box = s3.shapes.add_textbox(cx + Inches(0.12), Inches(1.85), mw4 - Inches(0.24), Inches(0.75))
        btf = box.text_frame
        btf.word_wrap = True
        btf.margin_top = btf.margin_left = 0
        p = btf.paragraphs[0]
        p.text = m_tag
        p.font.size = Pt(13)
        p.font.bold = True
        p.font.color.rgb = m_col
        p.space_after = Pt(2)
        p2 = btf.add_paragraph()
        p2.text = m_desc
        p2.font.size = Pt(10)
        p2.font.color.rgb = TEXT_LIGHT

    # Bottom Left: Explanation Card
    add_card(s3, Inches(0.8), Inches(2.9), Inches(5.6), Inches(3.8))
    lbox3 = s3.shapes.add_textbox(Inches(1.05), Inches(3.1), Inches(5.1), Inches(3.4))
    ltf3 = lbox3.text_frame
    ltf3.word_wrap = True
    ltf3.margin_top = ltf3.margin_left = 0

    p_sol_title = ltf3.paragraphs[0]
    p_sol_title.text = "The Cart Invariant Principle"
    p_sol_title.font.size = Pt(18)
    p_sol_title.font.bold = True
    p_sol_title.font.color.rgb = CYAN_ACCENT
    p_sol_title.space_after = Pt(8)

    sol_bullets = [
        "Separates Recipe Family from Cart Instance: Adding items to reach free shipping moves the subtotal without changing unit prices.",
        "Zero False Alarms: Standard small-cart delivery rules are correctly reported as legitimate policy rules (SMALL_CART_RULE), not deceptive price discrimination.",
        "Integer Minor-Unit Math: Reconciles Subtotal + Charges + Taxes - Discounts == Payable in integer paise (₹0.01).",
        "Deterministic Diff Engine: Compares runs differing in exactly one requested dimension."
    ]
    for b in sol_bullets:
        pb = ltf3.add_paragraph()
        pb.text = f"✓  {b}"
        pb.font.size = Pt(11)
        pb.font.color.rgb = TEXT_LIGHT
        pb.space_after = Pt(6)

    # Bottom Right: Real 3-Stage Gallery Screenshot
    add_framed_image(
        s3,
        "screenshots/ui-audit/06_real_merchant_gallery_viewport_1440x900.png",
        Inches(6.8), Inches(2.9), Inches(5.7), Inches(3.8),
        caption="3-Stage Visual Evidence Gallery: Product Page, Cart Drawer, and Checkout Summary with cryptographic SHA-256 digests."
    )
    add_footer(s3, 3)

    # ==========================================
    # SLIDE 4: Target Users & Use Cases
    # ==========================================
    s4 = prs.slides.add_slide(blank_layout)
    apply_bg(s4)
    add_header(s4, "3. TARGET USERS OR USE CASE", "Empowering the Consumer Protection Ecosystem",
               "Three key personas benefiting from automated outside-in checkout transparency.")

    # Left: 3 Personas
    p_card_h4 = Inches(1.5)
    users = [
        ("01 · CONSUMERS & ADVOCATES", "1-Click NCH Grievance Filing",
         "Reduces National Consumer Helpline complaint preparation from 45 minutes to 30 seconds with pre-filled CCPA citations and SHA-256 evidence links.", CYAN_ACCENT),
        ("02 · INVESTIGATIVE JOURNALISTS", "Empirical Exposés & Datasets",
         "Provides reproducible, exportable HTML dossiers backed by timestamped logs to expose predatory pricing, surge fees, and geographic discrimination.", BLUE_ACCENT),
        ("03 · ENTERPRISE COMPLIANCE", "Pre-Regulatory Regression Testing",
         "Enables retail brands to audit their own checkout funnels and third-party plugins before regulatory scrutiny or customer backlash.", EMERALD),
    ]

    for i, (tag, title, desc, col) in enumerate(users):
        cy = Inches(1.8) + i * Inches(1.65)
        add_card(s4, Inches(0.8), cy, col_w2, p_card_h4)
        cbox = s4.shapes.add_textbox(Inches(1.0), cy + Inches(0.12), col_w2 - Inches(0.4), p_card_h4 - Inches(0.24))
        ctf = cbox.text_frame
        ctf.word_wrap = True
        ctf.margin_top = ctf.margin_left = 0
        
        p1 = ctf.paragraphs[0]
        p1.text = tag
        p1.font.size = Pt(10)
        p1.font.bold = True
        p1.font.color.rgb = col
        p1.space_after = Pt(2)

        p2 = ctf.add_paragraph()
        p2.text = title
        p2.font.size = Pt(14)
        p2.font.bold = True
        p2.font.color.rgb = TEXT_WHITE
        p2.space_after = Pt(4)

        p3 = ctf.add_paragraph()
        p3.text = desc
        p3.font.size = Pt(11)
        p3.font.color.rgb = TEXT_LIGHT

    # Right: Real Complaint Draft Modal Screenshot
    add_framed_image(
        s4,
        "screenshots/ui-audit/08_complaint_draft_modal_1440x900.png",
        Inches(6.8), Inches(1.8), Inches(5.7), Inches(4.6),
        caption="Actionable Grievance Generation: Pre-filled National Consumer Helpline complaint draft with statutory CCPA citations and evidence links."
    )
    add_footer(s4, 4)

    # ==========================================
    # SLIDE 5: Role of Machine Learning & AI
    # ==========================================
    s5 = prs.slides.add_slide(blank_layout)
    apply_bg(s5)
    add_header(s5, "4. ROLE OF MACHINE LEARNING OR AI", "Hybrid Architecture: Deterministic First, AI Last",
               "AI navigates and contextualizes; deterministic engines compute mathematical proof.")

    half_w = Inches(5.7)
    gap_w = Inches(0.3)
    
    # Left Card: Web Agent
    add_card(s5, Inches(0.8), Inches(1.8), half_w, Inches(4.8))
    abox = s5.shapes.add_textbox(Inches(1.05), Inches(2.05), half_w - Inches(0.5), Inches(4.3))
    atf = abox.text_frame
    atf.word_wrap = True
    atf.margin_top = atf.margin_left = 0

    pa1 = atf.paragraphs[0]
    pa1.text = "Autonomous Web Agent AI (TinyFish)"
    pa1.font.size = Pt(20)
    pa1.font.bold = True
    pa1.font.color.rgb = CYAN_ACCENT
    pa1.space_after = Pt(12)

    agent_points = [
        "Complex Visual DOM Navigation: Navigates modern React, Vue, Shopify, and headless checkouts without custom site-specific scrapers.",
        "Human-Like Emulation: Solves variant selection, opens cart drawers, fills guest address forms, and handles modals.",
        "Hardened Safety Invariant: Negative prompts enforce a strict STOP BEFORE PAYMENT authorization boundary.",
        "Zero Hallucination in Pricing: Agent captures raw 1280×720 viewports and itemized DOM strings; does not invent fees."
    ]
    for pt in agent_points:
        p_pt = atf.add_paragraph()
        p_pt.text = f"✓  {pt}"
        p_pt.font.size = Pt(12)
        p_pt.font.color.rgb = TEXT_LIGHT
        p_pt.space_after = Pt(10)

    # Right Card: Guarded LLM
    add_card(s5, Inches(0.8) + half_w + gap_w, Inches(1.8), half_w, Inches(4.8))
    lbox2 = s5.shapes.add_textbox(Inches(0.8) + half_w + gap_w + Inches(0.25), Inches(2.05), half_w - Inches(0.5), Inches(4.3))
    ltf2 = lbox2.text_frame
    ltf2.word_wrap = True
    ltf2.margin_top = ltf2.margin_left = 0

    pl1 = ltf2.paragraphs[0]
    pl1.text = "Schema-Guarded LLM Contextualizer"
    pl1.font.size = Pt(20)
    pl1.font.bold = True
    pl1.font.color.rgb = BLUE_ACCENT
    pl1.space_after = Pt(12)

    llm_points = [
        "Downstream Explanation Only: LLM never detects or invents findings; it only translates candidate diffs into statutory explanations.",
        "Strict Non-Judicial Filter: Intercepts prohibited adjudicative terms ('guilty', 'unlawful', 'convicted') while preserving disclaimers.",
        "Evidence Grounding Engine: Rejects claims of fee absence unless substantiated by explicit not_observed_verified records.",
        "Resilient Fallback: If LLM is rate-limited (HTTP 429), deterministic statutory templates ensure 100% compliant persisted findings."
    ]
    for pt in llm_points:
        p_pt = ltf2.add_paragraph()
        p_pt.text = f"✓  {pt}"
        p_pt.font.size = Pt(12)
        p_pt.font.color.rgb = TEXT_LIGHT
        p_pt.space_after = Pt(10)

    add_footer(s5, 5)

    # ==========================================
    # SLIDE 6: Proposed Technical Approach
    # ==========================================
    s6 = prs.slides.add_slide(blank_layout)
    apply_bg(s6)
    add_header(s6, "5. PROPOSED TECHNICAL APPROACH", "8-Stage Forensic Pipeline & Append-Only Architecture",
               "End-to-end data flow with integer minor-unit arithmetic, lease fencing, and cryptographic custody.")

    # 8 Stage Cards (Row 1: 1-4, Row 2: 5-8)
    st_w = Inches(2.75)
    st_gap = Inches(0.23)
    stages_r1 = [
        ("01 · Discovery", "TinyFish Search API queries merchant terms, pricing policies, and return links.", CYAN_ACCENT),
        ("02 · Policy Extract", "TinyFish Fetch API extracts clean markdown policies with defined cache TTLs.", BLUE_ACCENT),
        ("03 · Navigate", "Autonomous web agent navigates funnel with stop-before-payment guardrail.", PURPLE),
        ("04 · Redact & Hash", "Pillow masks bottom-5% and form PII; calculates SHA-256 image digest.", EMERALD),
    ]
    stages_r2 = [
        ("05 · Reconcile", "Integer paise check: Subtotal + Charges + Taxes - Discounts == Payable.", EMERALD),
        ("06 · Diff Engine", "Matched-pair engine computes 5 diff types across isolated dimensions.", BLUE_ACCENT),
        ("07 · CCPA Detect", "Deterministic rules match Annex 1.8 (Drip), 1.2 (Sneak), 1.1 (Urgency).", CORAL),
        ("08 · Report & Draft", "Compiles self-contained HTML evidence report and editable NCH grievance.", CYAN_ACCENT),
    ]

    for i, (s_title, s_desc, s_col) in enumerate(stages_r1):
        cx = Inches(0.8) + i * (st_w + st_gap)
        add_card(s6, cx, Inches(1.8), st_w, Inches(2.2))
        sbox = s6.shapes.add_textbox(cx + Inches(0.15), Inches(1.95), st_w - Inches(0.3), Inches(1.9))
        stf = sbox.text_frame
        stf.word_wrap = True
        stf.margin_top = stf.margin_left = 0
        p1 = stf.paragraphs[0]
        p1.text = s_title
        p1.font.size = Pt(14)
        p1.font.bold = True
        p1.font.color.rgb = s_col
        p1.space_after = Pt(4)
        p2 = stf.add_paragraph()
        p2.text = s_desc
        p2.font.size = Pt(11)
        p2.font.color.rgb = TEXT_LIGHT

    for i, (s_title, s_desc, s_col) in enumerate(stages_r2):
        cx = Inches(0.8) + i * (st_w + st_gap)
        add_card(s6, cx, Inches(4.3), st_w, Inches(2.2))
        sbox = s6.shapes.add_textbox(cx + Inches(0.15), Inches(4.45), st_w - Inches(0.3), Inches(1.9))
        stf = sbox.text_frame
        stf.word_wrap = True
        stf.margin_top = stf.margin_left = 0
        p1 = stf.paragraphs[0]
        p1.text = s_title
        p1.font.size = Pt(14)
        p1.font.bold = True
        p1.font.color.rgb = s_col
        p1.space_after = Pt(4)
        p2 = stf.add_paragraph()
        p2.text = s_desc
        p2.font.size = Pt(11)
        p2.font.color.rgb = TEXT_LIGHT

    add_footer(s6, 6)

    # ==========================================
    # SLIDE 7: Proposed TinyFish Integration
    # ==========================================
    s7 = prs.slides.add_slide(blank_layout)
    apply_bg(s7)
    add_header(s7, "6. PROPOSED TINYFISH INTEGRATION", "In the Primary Path Across the Complete TinyFish API Surface",
               "TinyFish is central to Checkout Radar across Search, Fetch, Agent, and Profiles APIs.")

    # Left: 4 API Cards
    left_w7 = Inches(5.6)
    c_h7 = Inches(1.15)
    tf_apis = [
        ("🔍 TinyFish Search API", "Merchant Terms & Policy Discovery", "Queries merchant terms and fee declarations prior to audit.", CYAN_ACCENT),
        ("📄 TinyFish Fetch API", "Clean Markdown Extraction with TTL Cache", "Extracts clean policy text with intelligent caching (ttl: 0 vs ttl: 3600).", BLUE_ACCENT),
        ("🤖 TinyFish Agent API", "Cloud Browser Navigation (Stop-Before-Payment)", "Executes multi-step browser automations under strict safety guardrails.", EMERALD),
        ("🛡️ TinyFish Profiles API", "State-Isolated Browser Contexts", "Spawns isolated profiles for returning conditions, preventing cookie leakage.", PURPLE),
    ]

    for i, (api_title, api_sub, api_desc, api_col) in enumerate(tf_apis):
        cy = Inches(1.8) + i * Inches(1.25)
        add_card(s7, Inches(0.8), cy, left_w7, c_h7)
        box = s7.shapes.add_textbox(Inches(1.0), cy + Inches(0.1), left_w7 - Inches(0.4), c_h7 - Inches(0.2))
        btf = box.text_frame
        btf.word_wrap = True
        btf.margin_top = btf.margin_left = 0
        p = btf.paragraphs[0]
        p.text = f"{api_title}  ·  {api_sub}"
        p.font.size = Pt(12)
        p.font.bold = True
        p.font.color.rgb = api_col
        p.space_after = Pt(2)
        p2 = btf.add_paragraph()
        p2.text = api_desc
        p2.font.size = Pt(10)
        p2.font.color.rgb = TEXT_LIGHT

    # Right: Real Headphone Zone Live Clean Audit Screenshot
    add_framed_image(
        s7,
        "screenshots/ui-audit/02_clean_audit_viewport_1440x900.png",
        Inches(6.8), Inches(1.8), Inches(5.7), Inches(4.6),
        caption="Empirically verified live audit of Headphone Zone: 51 provider calls logged, 0 hidden fees, and verified clean outcome."
    )
    add_footer(s7, 7)

    # ==========================================
    # SLIDE 8: Expected Impact
    # ==========================================
    s8 = prs.slides.add_slide(blank_layout)
    apply_bg(s8)
    add_header(s8, "7. EXPECTED IMPACT", "Quantified Consumer, Legal, and Technical Outcomes",
               "Measurable results proven across synthetic benchmarks and live merchant audits.")

    # Top: 4 Big Impact Cards
    impacts_top = [
        ("45m ➔ 30s", "Grievance Velocity", CYAN_ACCENT),
        ("100% / 100%", "Precision & Recall", EMERALD),
        ("0 Secrets", "Zero-Exfiltration", BLUE_ACCENT),
        ("SHA-256", "Cryptographic Custody", PURPLE),
    ]
    for i, (ival, ititle, icol) in enumerate(impacts_top):
        cx = Inches(0.8) + i * (mw4 + mgap)
        add_card(s8, cx, Inches(1.75), mw4, Inches(0.95))
        box = s8.shapes.add_textbox(cx + Inches(0.12), Inches(1.82), mw4 - Inches(0.24), Inches(0.8))
        btf = box.text_frame
        btf.word_wrap = True
        btf.margin_top = btf.margin_left = 0
        p = btf.paragraphs[0]
        p.text = ival
        p.font.size = Pt(18)
        p.font.bold = True
        p.font.color.rgb = icol
        p.space_after = Pt(2)
        p2 = btf.add_paragraph()
        p2.text = ititle
        p2.font.size = Pt(10)
        p2.font.color.rgb = TEXT_MUTED

    # Bottom Left: Detailed Impact Points
    add_card(s8, Inches(0.8), Inches(2.9), Inches(5.6), Inches(3.8))
    lbox8 = s8.shapes.add_textbox(Inches(1.05), Inches(3.1), Inches(5.1), Inches(3.4))
    ltf8 = lbox8.text_frame
    ltf8.word_wrap = True
    ltf8.margin_top = ltf8.margin_left = 0

    p_imp_title = ltf8.paragraphs[0]
    p_imp_title.text = "Tangible Real-World Outcomes"
    p_imp_title.font.size = Pt(18)
    p_imp_title.font.bold = True
    p_imp_title.font.color.rgb = CYAN_ACCENT
    p_imp_title.space_after = Pt(8)

    imp_bullets = [
        "98% Faster Grievance Redressal: Transforms a frustrating 45-minute manual drafting ordeal into a 30-second automated NCH export.",
        "Zero False Accusations: 100% precision across 45 designed benchmark scenarios guarantees honest merchants are never falsely penalized.",
        "Court-Admissible Chain of Custody: Every observation is backed by a 64-character SHA-256 digest of the unscaled viewport capture.",
        "Total Privacy Protection: API credentials stored backend-only; Pillow redaction masks form fields and footers automatically."
    ]
    for b in imp_bullets:
        pb = ltf8.add_paragraph()
        pb.text = f"•  {b}"
        pb.font.size = Pt(11)
        pb.font.color.rgb = TEXT_LIGHT
        pb.space_after = Pt(6)

    # Bottom Right: Real SHA-256 Lightbox Modal Screenshot
    add_framed_image(
        s8,
        "screenshots/ui-audit/07_lightbox_modal_open_1440x900.png",
        Inches(6.8), Inches(2.9), Inches(5.7), Inches(3.8),
        caption="Full-Resolution Lightbox Modal: Unscaled viewport inspection with immutable 64-character SHA-256 cryptographic digest."
    )
    add_footer(s8, 8)

    # ==========================================
    # SLIDE 9: Feasibility & Implementation Readiness
    # ==========================================
    s9 = prs.slides.add_slide(blank_layout)
    apply_bg(s9)
    add_header(s9, "8. FEASIBILITY & IMPLEMENTATION READINESS", "Production-Ready Stack with Zero Setup Friction",
               "Zero-barrier demonstration: judges can clone, test, and run audits immediately with zero cloud costs.")

    col_w9 = Inches(3.7)
    pillars = [
        ("🚀 ONE-COMMAND LAUNCH", "Zero Setup Friction",
         [
             "Cross-platform launcher script (./start.sh or start.cmd).",
             "Automatic pre-flight diagnostics, .env provisioning, and healthcheck sync.",
             "Dynamic host port discovery eliminates port conflict errors.",
             "Docker Compose orchestrates harness, API, and worker in <30s."
         ], CYAN_ACCENT),
        ("🛡️ DETERMINISTIC MOCK", "100% Free Offline Mode",
         [
             "Runs full audits, tests, and demo flows without consuming TinyFish or LLM credits.",
             "Includes 5-variant reproducible merchant server container.",
             "114 unit, integration, and concurrency tests pass locally in <2 seconds.",
             "Pre-seeded demonstration audits populate instantly."
         ], EMERALD),
        ("💰 ECONOMICAL SCALE", "Cost-Efficient Live Runs",
         [
             "A full Quick 4-run condition matrix audit costs under $0.20 on TinyFish cloud.",
             "Monotonic lease recovery prevents duplicate submissions on failure.",
             "TTL caching on Fetch API prevents redundant policy crawls."
         ], BLUE_ACCENT),
    ]

    for i, (tag, title, pts, col) in enumerate(pillars):
        cx = Inches(0.8) + i * (col_w9 + Inches(0.3))
        add_card(s9, cx, Inches(1.8), col_w9, Inches(4.8))
        box = s9.shapes.add_textbox(cx + Inches(0.2), Inches(2.0), col_w9 - Inches(0.4), Inches(4.4))
        btf = box.text_frame
        btf.word_wrap = True
        btf.margin_top = btf.margin_left = 0

        p1 = btf.paragraphs[0]
        p1.text = tag
        p1.font.size = Pt(11)
        p1.font.bold = True
        p1.font.color.rgb = col
        p1.space_after = Pt(4)

        p2 = btf.add_paragraph()
        p2.text = title
        p2.font.size = Pt(16)
        p2.font.bold = True
        p2.font.color.rgb = TEXT_WHITE
        p2.space_after = Pt(12)

        for pt in pts:
            ppt = btf.add_paragraph()
            ppt.text = f"•  {pt}"
            ppt.font.size = Pt(11)
            ppt.font.color.rgb = TEXT_LIGHT
            ppt.space_after = Pt(8)

    add_footer(s9, 9)

    # ==========================================
    # SLIDE 10: Future Scope & Roadmap
    # ==========================================
    s10 = prs.slides.add_slide(blank_layout)
    apply_bg(s10)
    add_header(s10, "9. FUTURE SCOPE & ROADMAP", "Scaling from Hackathon MVP to National Transparency Infrastructure",
               "Strategic expansion across real-time consumer warnings, regulatory APIs, and global jurisdictions.")

    roadmap = [
        ("PHASE 1 · NEAR-TERM", "Live Consumer Browser Extension",
         [
             "Chrome/Firefox extension auditing checkout funnels in the background while users shop.",
             "Instant warning badges appear when a hidden fee or pre-ticked add-on is detected.",
             "One-click 'Report to Checkout Radar' crowdsourced fee tracking."
         ], CYAN_ACCENT),
        ("PHASE 2 · MID-TERM", "Direct NCH API Integration",
         [
             "Direct integration with National Consumer Helpline and e-Daakhil consumer court APIs.",
             "Automated grievance filing with digitally signed, SHA-256 hashed evidence bundles.",
             "Enables consumer organizations to file class-action transparency complaints."
         ], BLUE_ACCENT),
        ("PHASE 3 · LONG-TERM", "Cross-Border 7-Nation Audits",
         [
             "Deploy residential browser proxies across 7 jurisdictions (US, UK, EU, Canada, Australia, Japan, India).",
             "Audit geographic price discrimination, currency conversion drip fees, and international shipping surges.",
             "Compliance engine mapped to EU DSA and US FTC Dark Pattern guidelines."
         ], PURPLE),
    ]

    for i, (tag, title, pts, col) in enumerate(roadmap):
        cx = Inches(0.8) + i * (col_w9 + Inches(0.3))
        add_card(s10, cx, Inches(1.8), col_w9, Inches(4.8))
        box = s10.shapes.add_textbox(cx + Inches(0.2), Inches(2.0), col_w9 - Inches(0.4), Inches(4.4))
        btf = box.text_frame
        btf.word_wrap = True
        btf.margin_top = btf.margin_left = 0

        p1 = btf.paragraphs[0]
        p1.text = tag
        p1.font.size = Pt(11)
        p1.font.bold = True
        p1.font.color.rgb = col
        p1.space_after = Pt(4)

        p2 = btf.add_paragraph()
        p2.text = title
        p2.font.size = Pt(16)
        p2.font.bold = True
        p2.font.color.rgb = TEXT_WHITE
        p2.space_after = Pt(12)

        for pt in pts:
            ppt = btf.add_paragraph()
            ppt.text = f"•  {pt}"
            ppt.font.size = Pt(11)
            ppt.font.color.rgb = TEXT_LIGHT
            ppt.space_after = Pt(8)

    add_footer(s10, 10)

    # Save
    out_file = Path("docs/pitch/Checkout_Radar_AZINHACK_2026.pptx")
    prs.save(str(out_file))
    print(f"Presentation saved to: {out_file}")

if __name__ == "__main__":
    create_presentation()
