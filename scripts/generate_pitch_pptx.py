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
    BG_COLOR = RGBColor(8, 12, 20)        # #080c14
    CARD_BG = RGBColor(14, 22, 38)        # #0e1626
    CARD_BORDER = RGBColor(35, 49, 72)    # #233148
    BLUE_ACCENT = RGBColor(59, 130, 246)  # #3b82f6
    CYAN_ACCENT = RGBColor(56, 189, 248)  # #38bdf8
    EMERALD = RGBColor(16, 185, 129)      # #10b981
    CORAL = RGBColor(239, 68, 68)         # #ef4444
    AMBER = RGBColor(245, 158, 11)        # #f59e0b
    PURPLE = RGBColor(139, 92, 246)       # #8b5cf6
    TEXT_WHITE = RGBColor(255, 255, 255)
    TEXT_LIGHT = RGBColor(203, 213, 225)  # #cbd5e1
    TEXT_MUTED = RGBColor(148, 163, 184)  # #94a3b8

    def apply_bg(slide):
        bg_shape = slide.shapes.add_shape(
            MSO_SHAPE.RECTANGLE, 0, 0, prs.slide_width, prs.slide_height
        )
        bg_shape.fill.solid()
        bg_shape.fill.fore_color.rgb = BG_COLOR
        bg_shape.line.fill.background()
        return bg_shape

    def add_header(slide, tag_text, title_text, subtitle_text=None):
        header_box = slide.shapes.add_textbox(Inches(0.8), Inches(0.4), Inches(11.7), Inches(1.3))
        tf = header_box.text_frame
        tf.word_wrap = True
        tf.margin_left = tf.margin_top = tf.margin_right = tf.margin_bottom = 0

        # Tag
        p_tag = tf.paragraphs[0]
        p_tag.text = tag_text.upper()
        p_tag.font.name = "Arial"
        p_tag.font.size = Pt(11)
        p_tag.font.bold = True
        p_tag.font.color.rgb = CYAN_ACCENT
        p_tag.space_after = Pt(4)

        # Title
        p_title = tf.add_paragraph()
        p_title.text = title_text
        p_title.font.name = "Arial"
        p_title.font.size = Pt(26)
        p_title.font.bold = True
        p_title.font.color.rgb = TEXT_WHITE
        p_title.space_after = Pt(4)

        # Subtitle
        if subtitle_text:
            p_sub = tf.add_paragraph()
            p_sub.text = subtitle_text
            p_sub.font.name = "Arial"
            p_sub.font.size = Pt(13)
            p_sub.font.color.rgb = TEXT_MUTED

    def add_footer(slide, current_page, total_pages=10):
        footer_box = slide.shapes.add_textbox(Inches(0.8), Inches(6.9), Inches(11.7), Inches(0.4))
        tf = footer_box.text_frame
        tf.word_wrap = True
        tf.margin_left = tf.margin_top = tf.margin_right = tf.margin_bottom = 0
        p = tf.paragraphs[0]
        p.text = f"Checkout Radar · AZINHACK 2026 Submission · Slide {current_page} of {total_pages}"
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

    # ==========================================
    # SLIDE 1: Title & Positioning
    # ==========================================
    s1 = prs.slides.add_slide(blank_layout)
    apply_bg(s1)

    # Hero Badge
    badge_card = s1.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(0.8), Inches(0.8), Inches(5.8), Inches(0.45))
    badge_card.fill.solid()
    badge_card.fill.fore_color.rgb = RGBColor(23, 37, 84) # Deep blue
    badge_card.line.color.rgb = BLUE_ACCENT
    badge_tf = badge_card.text_frame
    badge_tf.margin_left = Inches(0.2)
    p_b = badge_tf.paragraphs[0]
    p_b.text = "AZINHACK 2026 · INNOVATION & CONSUMER TRANSPARENCY"
    p_b.font.name = "Arial"
    p_b.font.size = Pt(10)
    p_b.font.bold = True
    p_b.font.color.rgb = CYAN_ACCENT

    # Big Title
    title_box = s1.shapes.add_textbox(Inches(0.8), Inches(1.4), Inches(11.7), Inches(2.2))
    tf1 = title_box.text_frame
    tf1.word_wrap = True
    tf1.margin_left = tf1.margin_top = 0

    p_main = tf1.paragraphs[0]
    p_main.text = "CHECKOUT RADAR"
    p_main.font.name = "Arial"
    p_main.font.size = Pt(44)
    p_main.font.bold = True
    p_main.font.color.rgb = TEXT_WHITE
    p_main.space_after = Pt(8)

    p_tagline = tf1.add_paragraph()
    p_tagline.text = "Outside-In Checkout Flow Auditor & CCPA Dark Pattern Detector"
    p_tagline.font.name = "Arial"
    p_tagline.font.size = Pt(22)
    p_tagline.font.bold = True
    p_tagline.font.color.rgb = CYAN_ACCENT
    p_tagline.space_after = Pt(10)

    p_desc = tf1.add_paragraph()
    p_desc.text = "Deploying autonomous TinyFish browser agents across controlled condition matrices to turn subjective dark pattern claims into reproducible, cryptographic, screenshot-backed empirical evidence."
    p_desc.font.name = "Arial"
    p_desc.font.size = Pt(14)
    p_desc.font.color.rgb = TEXT_LIGHT

    # 4 Metric Highlights at the bottom
    metrics = [
        ("114 / 114", "Tests Passing (CI Tested)", EMERALD),
        ("3 / 3", "Demo Flows Verified", CYAN_ACCENT),
        ("SHA-256", "Cryptographic Chain of Custody", BLUE_ACCENT),
        ("Zero Credits", "Deterministic Offline Mock", PURPLE),
    ]
    card_w = Inches(2.75)
    gap = Inches(0.23)
    start_x = Inches(0.8)
    for i, (val, label, color) in enumerate(metrics):
        cx = start_x + i * (card_w + gap)
        add_card(s1, cx, Inches(4.3), card_w, Inches(1.6))
        
        mbox = s1.shapes.add_textbox(cx + Inches(0.15), Inches(4.45), card_w - Inches(0.3), Inches(1.3))
        mtf = mbox.text_frame
        mtf.word_wrap = True
        mtf.margin_top = mtf.margin_left = 0
        
        pv = mtf.paragraphs[0]
        pv.text = val
        pv.font.name = "Arial"
        pv.font.size = Pt(28)
        pv.font.bold = True
        pv.font.color.rgb = color
        pv.space_after = Pt(4)
        
        pl = mtf.add_paragraph()
        pl.text = label
        pl.font.name = "Arial"
        pl.font.size = Pt(11)
        pl.font.color.rgb = TEXT_MUTED

    add_footer(s1, 1)

    # ==========================================
    # SLIDE 2: Problem Statement
    # ==========================================
    s2 = prs.slides.add_slide(blank_layout)
    apply_bg(s2)
    add_header(s2, "1. PROBLEM STATEMENT", "The Hidden Fee Epidemic & The Outside-In Evidence Gap", 
               "Indian consumers face systematic late-stage fee disclosure without any tooling for admissible legal proof.")

    col_w = Inches(3.7)
    col_gap = Inches(0.3)
    c_y = Inches(1.8)
    c_h = Inches(4.8)

    problems = [
        ("💸 Late-Stage Fee Inflation",
         "The Drip Pricing Trap",
         [
             "Surge fees, handling charges, packaging levies, and convenience fees appear only on the final payment screen.",
             "Consumers invest 10–15 minutes navigating products and entering addresses before the true payable price is revealed.",
             "Violates Section 18 of the Consumer Protection Act, 2019."
         ], CORAL),
        ("⚖️ Regulatory Mandate",
         "CCPA November 2023 Guidelines",
         [
             "CCPA officially notified 13 prohibited dark patterns on 30 Nov 2023.",
             "Annex 1.8 strictly bans Drip Pricing (concealing mandatory costs).",
             "Annex 1.2 bans Basket Sneaking (pre-ticked add-ons).",
             "Annex 1.1 bans False Urgency (falsely implying urgency or resetting timers)."
         ], AMBER),
        ("🔍 The Evidence Bottleneck",
         "Lack of Empirical Tooling",
         [
             "Existing audit tools cater exclusively to internal platform teams.",
             "Consumers, researchers, and journalists cannot capture legally admissible, reproducible proof.",
             "Single-page apps (SPAs) defeat static web scrapers, leaving deceptive checkouts unmonitored."
         ], BLUE_ACCENT),
    ]

    for i, (tag, heading, points, accent) in enumerate(problems):
        cx = Inches(0.8) + i * (col_w + col_gap)
        add_card(s2, cx, c_y, col_w, c_h)

        pbox = s2.shapes.add_textbox(cx + Inches(0.25), c_y + Inches(0.25), col_w - Inches(0.5), c_h - Inches(0.5))
        ptf = pbox.text_frame
        ptf.word_wrap = True
        ptf.margin_top = ptf.margin_left = 0

        p1 = ptf.paragraphs[0]
        p1.text = tag
        p1.font.name = "Arial"
        p1.font.size = Pt(13)
        p1.font.bold = True
        p1.font.color.rgb = accent
        p1.space_after = Pt(6)

        p2 = ptf.add_paragraph()
        p2.text = heading
        p2.font.name = "Arial"
        p2.font.size = Pt(18)
        p2.font.bold = True
        p2.font.color.rgb = TEXT_WHITE
        p2.space_after = Pt(14)

        for pt in points:
            p_pt = ptf.add_paragraph()
            p_pt.text = f"•  {pt}"
            p_pt.font.name = "Arial"
            p_pt.font.size = Pt(12)
            p_pt.font.color.rgb = TEXT_LIGHT
            p_pt.space_after = Pt(10)

    add_footer(s2, 2)

    # ==========================================
    # SLIDE 3: Proposed Solution
    # ==========================================
    s3 = prs.slides.add_slide(blank_layout)
    apply_bg(s3)
    add_header(s3, "2. PROPOSED SOLUTION", "Matched-Pair Differential Auditing Engine",
               "Turning subjective allegations into controlled, reproducible, screenshot-backed empirical proof.")

    # Left card: Concept
    left_w = Inches(5.0)
    add_card(s3, Inches(0.8), Inches(1.8), left_w, Inches(4.8))
    lbox = s3.shapes.add_textbox(Inches(1.05), Inches(2.05), left_w - Inches(0.5), Inches(4.3))
    ltf = lbox.text_frame
    ltf.word_wrap = True
    ltf.margin_top = ltf.margin_left = 0

    p_sol_h = ltf.paragraphs[0]
    p_sol_h.text = "Controlled Scientific Method"
    p_sol_h.font.name = "Arial"
    p_sol_h.font.size = Pt(20)
    p_sol_h.font.bold = True
    p_sol_h.font.color.rgb = CYAN_ACCENT
    p_sol_h.space_after = Pt(10)

    sol_bullets = [
        "Not a scraper: Checkout Radar executes controlled behavioral experiments.",
        "Differential Principle: Compares two runs that differ in exactly one requested dimension while holding all other controls fixed.",
        "Integer Minor-Unit Math: Reconciles all charges in integer paise (₹0.01) to eliminate rounding errors.",
        "The Cart Invariant: Separates Recipe Family from Cart Instance. Quantity changes do NOT trigger false price variance alarms.",
        "Cryptographic Custody: 1280×720 viewports redacted with Pillow and hashed with SHA-256."
    ]
    for b in sol_bullets:
        pb = ltf.add_paragraph()
        pb.text = f"✓  {b}"
        pb.font.name = "Arial"
        pb.font.size = Pt(12)
        pb.font.color.rgb = TEXT_LIGHT
        pb.space_after = Pt(10)

    # Right side: 4 Condition Matrix Cards
    r_x = Inches(6.1)
    r_w = Inches(6.4)
    r_h = Inches(1.05)
    matrix_cards = [
        ("📍 Location Effect", "Tests Tier-1 Metro vs Tier-2/3 Pincodes (e.g. 110001 vs 492001)", "Controls: Session state, cart tier, recipe family", CYAN_ACCENT),
        ("👤 Session Effect", "Tests Fresh Guest Profile vs Returning Customer Profile", "Controls: Delivery pincode, cart tier, recipe family", BLUE_ACCENT),
        ("🛒 Cart Threshold", "Tests Above Threshold (₹998) vs Below Threshold (₹499)", "Controls: Delivery pincode, session state, unit price", EMERALD),
        ("⏱️ Temporal Drift", "Tests Observation at t0 vs Re-observation at t1 across time", "Controls: All factors and cart recipe held fixed", PURPLE),
    ]

    for j, (m_title, m_desc, m_ctrl, m_col) in enumerate(matrix_cards):
        cy = Inches(1.8) + j * Inches(1.25)
        add_card(s3, r_x, cy, r_w, r_h)
        
        mbox = s3.shapes.add_textbox(r_x + Inches(0.2), cy + Inches(0.12), r_w - Inches(0.4), r_h - Inches(0.24))
        mtf = mbox.text_frame
        mtf.word_wrap = True
        mtf.margin_top = mtf.margin_left = 0
        
        pm1 = mtf.paragraphs[0]
        pm1.text = m_title
        pm1.font.name = "Arial"
        pm1.font.size = Pt(14)
        pm1.font.bold = True
        pm1.font.color.rgb = m_col
        pm1.space_after = Pt(2)
        
        pm2 = mtf.add_paragraph()
        pm2.text = f"{m_desc}  |  {m_ctrl}"
        pm2.font.name = "Arial"
        pm2.font.size = Pt(11)
        pm2.font.color.rgb = TEXT_MUTED

    add_footer(s3, 3)

    # ==========================================
    # SLIDE 4: Target Users & Use Cases
    # ==========================================
    s4 = prs.slides.add_slide(blank_layout)
    apply_bg(s4)
    add_header(s4, "3. TARGET USERS OR USE CASE", "Empowering Stakeholders Across the Consumer Protection Ecosystem",
               "Three primary personas benefiting from automated outside-in checkout transparency.")

    personas = [
        ("Consumers & Advocates",
         "Grievance Filing & NCH Redressal",
         [
             "Generate ready-to-file National Consumer Helpline (NCH) grievance drafts.",
             "Pre-filled with merchant identity, exact fee breakdown, and statutory CCPA citations.",
             "Includes tamper-evident SHA-256 evidence links that merchants cannot dispute.",
             "Reduces complaint preparation time from 45 minutes to 30 seconds."
         ], CYAN_ACCENT),
        ("Investigative Media",
         "Empirical Exposés & Research",
         [
             "Empirical, reproducible datasets on fee inflation, surge charges, and geographic discrimination.",
             "Export self-contained, offline HTML dossiers complete with high-res viewports.",
             "Enables data-driven investigative reporting on quick-commerce and retail cart practices."
         ], BLUE_ACCENT),
        ("Enterprise Compliance",
         "Proactive Pre-Regulatory Auditing",
         [
             "Outside-in regression testing for e-commerce brands before regulatory scrutiny.",
             "Audit internal Shopify, WooCommerce, or custom storefronts against CCPA 2023 rules.",
             "Identify unintended dark patterns introduced by third-party checkout plugins or apps."
         ], EMERALD),
    ]

    for i, (p_tag, p_head, p_pts, p_col) in enumerate(personas):
        cx = Inches(0.8) + i * (col_w + col_gap)
        add_card(s4, cx, c_y, col_w, c_h)

        pbox = s4.shapes.add_textbox(cx + Inches(0.25), c_y + Inches(0.25), col_w - Inches(0.5), c_h - Inches(0.5))
        ptf = pbox.text_frame
        ptf.word_wrap = True
        ptf.margin_top = ptf.margin_left = 0

        p1 = ptf.paragraphs[0]
        p1.text = p_tag
        p1.font.name = "Arial"
        p1.font.size = Pt(13)
        p1.font.bold = True
        p1.font.color.rgb = p_col
        p1.space_after = Pt(6)

        p2 = ptf.add_paragraph()
        p2.text = p_head
        p2.font.name = "Arial"
        p2.font.size = Pt(18)
        p2.font.bold = True
        p2.font.color.rgb = TEXT_WHITE
        p2.space_after = Pt(14)

        for pt in p_pts:
            ppt = ptf.add_paragraph()
            ppt.text = f"•  {pt}"
            ppt.font.name = "Arial"
            ppt.font.size = Pt(12)
            ppt.font.color.rgb = TEXT_LIGHT
            ppt.space_after = Pt(10)

    add_footer(s4, 4)

    # ==========================================
    # SLIDE 5: Role of Machine Learning or AI
    # ==========================================
    s5 = prs.slides.add_slide(blank_layout)
    apply_bg(s5)
    add_header(s5, "4. ROLE OF MACHINE LEARNING OR AI", "Hybrid Architecture: Deterministic First, AI Last",
               "AI navigates and contextualizes; deterministic engines compute mathematical proof.")

    # 2 Big Cards: Agent AI vs LLM Classifier
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
    pa1.font.name = "Arial"
    pa1.font.size = Pt(20)
    pa1.font.bold = True
    pa1.font.color.rgb = CYAN_ACCENT
    pa1.space_after = Pt(12)

    agent_points = [
        "Complex Visual DOM Navigation: Navigates modern React, Vue, Shopify, and headless checkout funnels without site-specific scrapers.",
        "Natural Human Emulation: Automatically solves variant selection, opens cart drawers, fills guest address forms, and handles modals.",
        "Hardened Safety Invariant: Negative prompts enforce a strict STOP BEFORE PAYMENT authorization boundary.",
        "Zero Hallucination in Pricing: Agent captures raw 1280×720 viewports and itemized DOM strings; does not invent fees."
    ]
    for pt in agent_points:
        p_pt = atf.add_paragraph()
        p_pt.text = f"✓  {pt}"
        p_pt.font.name = "Arial"
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
    pl1.font.name = "Arial"
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
        p_pt.font.name = "Arial"
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

    # 4 Architecture Columns (2 rows of 4 or 4 horizontal columns)
    stage_w = Inches(2.75)
    stage_gap = Inches(0.23)
    
    stages_row1 = [
        ("01 · Discovery", "TinyFish Search API queries merchant terms, pricing policies, and return links.", CYAN_ACCENT),
        ("02 · Extract", "TinyFish Fetch API extracts clean markdown policies with defined cache TTLs.", BLUE_ACCENT),
        ("03 · Navigate", "Autonomous web agent executes funnel with stop-before-payment guardrail.", PURPLE),
        ("04 · Redact & Hash", "Pillow masks bottom-5% and form PII; calculates SHA-256 image digest.", EMERALD),
    ]
    stages_row2 = [
        ("05 · Reconcile", "Strict minor-unit math check: Subtotal + Charges + Taxes - Discounts = Payable.", EMERALD),
        ("06 · Diff Engine", "Matched-pair analysis evaluates 5 diff types across isolated dimensions.", BLUE_ACCENT),
        ("07 · Detect", "Deterministic rules match CCPA Annex 1.8 (Drip), 1.2 (Sneak), 1.1 (Urgency).", CORAL),
        ("08 · Report", "Generates self-contained HTML evidence dossier and NCH complaint draft.", CYAN_ACCENT),
    ]

    for i, (s_title, s_desc, s_col) in enumerate(stages_row1):
        cx = Inches(0.8) + i * (stage_w + stage_gap)
        add_card(s6, cx, Inches(1.8), stage_w, Inches(2.2))
        sbox = s6.shapes.add_textbox(cx + Inches(0.15), Inches(1.95), stage_w - Inches(0.3), Inches(1.9))
        stf = sbox.text_frame
        stf.word_wrap = True
        stf.margin_top = stf.margin_left = 0
        p1 = stf.paragraphs[0]
        p1.text = s_title
        p1.font.name = "Arial"
        p1.font.size = Pt(15)
        p1.font.bold = True
        p1.font.color.rgb = s_col
        p1.space_after = Pt(6)
        p2 = stf.add_paragraph()
        p2.text = s_desc
        p2.font.name = "Arial"
        p2.font.size = Pt(11)
        p2.font.color.rgb = TEXT_LIGHT

    for i, (s_title, s_desc, s_col) in enumerate(stages_row2):
        cx = Inches(0.8) + i * (stage_w + stage_gap)
        add_card(s6, cx, Inches(4.3), stage_w, Inches(2.2))
        sbox = s6.shapes.add_textbox(cx + Inches(0.15), Inches(4.45), stage_w - Inches(0.3), Inches(1.9))
        stf = sbox.text_frame
        stf.word_wrap = True
        stf.margin_top = stf.margin_left = 0
        p1 = stf.paragraphs[0]
        p1.text = s_title
        p1.font.name = "Arial"
        p1.font.size = Pt(15)
        p1.font.bold = True
        p1.font.color.rgb = s_col
        p1.space_after = Pt(6)
        p2 = stf.add_paragraph()
        p2.text = s_desc
        p2.font.name = "Arial"
        p2.font.size = Pt(11)
        p2.font.color.rgb = TEXT_LIGHT

    add_footer(s6, 6)

    # ==========================================
    # SLIDE 7: Proposed TinyFish Integration
    # ==========================================
    s7 = prs.slides.add_slide(blank_layout)
    apply_bg(s7)
    add_header(s7, "6. PROPOSED TINYFISH INTEGRATION", "Deep Platform Integration Across the Complete API Surface",
               "TinyFish is in the main execution path across Search, Fetch, Agent, and Profiles APIs.")

    grid_w = Inches(5.7)
    grid_h = Inches(2.25)
    
    tf_apis = [
        ("🔍 TinyFish Search API",
         "Merchant Terms & Policy Discovery",
         "Discovers merchant declared terms of service, fee disclosures, and return policies during audit initiation without manual URL hunting.",
         CYAN_ACCENT),
        ("📄 TinyFish Fetch API",
         "Clean Markdown Extraction with TTL Caching",
         "Extracts clean policy text with intelligent caching: ttl: 0 for dynamic checkout flows, ttl: 3600 for static terms to conserve API quota.",
         BLUE_ACCENT),
        ("🤖 TinyFish Agent API",
         "Cloud Browser Navigation (Stop-Before-Payment)",
         "Executes multi-step browser automations across product, cart, and summary states under strict CCPA safety guardrails.",
         EMERALD),
        ("🛡️ TinyFish Profiles API",
         "State-Isolated Browser Contexts",
         "Spawns isolated browser context profiles for returning visitor conditions, preventing cookie and session leakage between matrix runs.",
         PURPLE),
    ]

    for idx, (api_title, api_sub, api_desc, api_col) in enumerate(tf_apis):
        row = idx // 2
        col = idx % 2
        cx = Inches(0.8) + col * (grid_w + Inches(0.3))
        cy = Inches(1.8) + row * (grid_h + Inches(0.3))
        
        add_card(s7, cx, cy, grid_w, grid_h)
        tbox = s7.shapes.add_textbox(cx + Inches(0.2), cy + Inches(0.18), grid_w - Inches(0.4), grid_h - Inches(0.36))
        ttf = tbox.text_frame
        ttf.word_wrap = True
        ttf.margin_top = ttf.margin_left = 0
        
        p1 = ttf.paragraphs[0]
        p1.text = api_title
        p1.font.name = "Arial"
        p1.font.size = Pt(16)
        p1.font.bold = True
        p1.font.color.rgb = api_col
        p1.space_after = Pt(2)
        
        p2 = ttf.add_paragraph()
        p2.text = api_sub
        p2.font.name = "Arial"
        p2.font.size = Pt(12)
        p2.font.bold = True
        p2.font.color.rgb = TEXT_WHITE
        p2.space_after = Pt(6)
        
        p3 = ttf.add_paragraph()
        p3.text = api_desc
        p3.font.name = "Arial"
        p3.font.size = Pt(11)
        p3.font.color.rgb = TEXT_LIGHT

    add_footer(s7, 7)

    # ==========================================
    # SLIDE 8: Expected Impact
    # ==========================================
    s8 = prs.slides.add_slide(blank_layout)
    apply_bg(s8)
    add_header(s8, "7. EXPECTED IMPACT", "Quantified Consumer, Legal, and Technical Outcomes",
               "Real-world impact metrics measured on synthetic benchmarks and live merchant audits.")

    # 4 Big impact cards
    impacts = [
        ("45 min ➔ 30 sec", "Consumer Grievance Velocity",
         "Reduces the time to document, verify, and draft an actionable CCPA dark pattern complaint from 45 minutes to 30 seconds with 1-click export.",
         CYAN_ACCENT),
        ("100% Precision", "Algorithmic Conformance",
         "100% precision, 100% recall, and F1 = 1.000 across 45 designed scenario bundles. Zero false alarms on negative controls.",
         EMERALD),
        ("Zero Exfiltration", "Security & Privacy Guarantee",
         "All API credentials stored backend-only. Raw keys never touch frontend storage, reports, or logs. Form PII redacted by Pillow.",
         BLUE_ACCENT),
        ("Admissible Evidence", "Cryptographic Chain of Custody",
         "Every observed charge is backed by an immutable SHA-256 hashed viewport, transforming anecdotal claims into legally admissible proof.",
         PURPLE),
    ]

    for i, (i_val, i_title, i_desc, i_col) in enumerate(impacts):
        row = i // 2
        col = i % 2
        cx = Inches(0.8) + col * (grid_w + Inches(0.3))
        cy = Inches(1.8) + row * (grid_h + Inches(0.3))
        
        add_card(s8, cx, cy, grid_w, grid_h)
        ibox = s8.shapes.add_textbox(cx + Inches(0.25), cy + Inches(0.18), grid_w - Inches(0.5), grid_h - Inches(0.36))
        itf = ibox.text_frame
        itf.word_wrap = True
        itf.margin_top = itf.margin_left = 0
        
        p1 = itf.paragraphs[0]
        p1.text = i_val
        p1.font.name = "Arial"
        p1.font.size = Pt(28)
        p1.font.bold = True
        p1.font.color.rgb = i_col
        p1.space_after = Pt(2)
        
        p2 = itf.add_paragraph()
        p2.text = i_title
        p2.font.name = "Arial"
        p2.font.size = Pt(14)
        p2.font.bold = True
        p2.font.color.rgb = TEXT_WHITE
        p2.space_after = Pt(6)
        
        p3 = itf.add_paragraph()
        p3.text = i_desc
        p3.font.name = "Arial"
        p3.font.size = Pt(11)
        p3.font.color.rgb = TEXT_LIGHT

    add_footer(s8, 8)

    # ==========================================
    # SLIDE 9: Feasibility
    # ==========================================
    s9 = prs.slides.add_slide(blank_layout)
    apply_bg(s9)
    add_header(s9, "8. FEASIBILITY & IMPLEMENTATION READINESS", "Production-Ready Stack with Deterministic Offline Defaults",
               "Zero-barrier demonstration: judges can clone, test, and run audits immediately with zero cloud costs.")

    col_w3 = Inches(3.7)
    feasibility_pillars = [
        ("🚀 One-Command Launch",
         "Zero Setup Friction",
         [
             "Cross-platform launcher script (./start.sh or start.cmd).",
             "Automatic pre-flight diagnostics, .env provisioning, and healthcheck synchronization.",
             "Dynamic host port discovery eliminates port conflict errors.",
             "Docker Compose orchestrates harness, API, and worker in <30s."
         ], CYAN_ACCENT),
        ("🛡️ Zero-Cost Offline Mock",
         "100% Deterministic Replay",
         [
             "Runs full audits, tests, and demo flows without consuming TinyFish or LLM credits.",
             "Includes 5-variant reproducible merchant server container.",
             "114 unit, integration, and concurrency tests pass locally in <2 seconds.",
             "Pre-seeded demonstration audits populate instantly."
         ], EMERALD),
        ("💰 Cost-Efficient Scale",
         "Economical Live Execution",
         [
             "A full Quick 4-run condition matrix audit costs under $0.20 on TinyFish cloud.",
             "Monotonic lease recovery prevents duplicate submissions on failure.",
             "TTL caching on Fetch API prevents redundant policy crawls."
         ], BLUE_ACCENT),
    ]

    for i, (f_tag, f_head, f_pts, f_col) in enumerate(feasibility_pillars):
        cx = Inches(0.8) + i * (col_w3 + col_gap)
        add_card(s9, cx, c_y, col_w3, c_h)

        fbox = s9.shapes.add_textbox(cx + Inches(0.25), c_y + Inches(0.25), col_w3 - Inches(0.5), c_h - Inches(0.5))
        ftf = fbox.text_frame
        ftf.word_wrap = True
        ftf.margin_top = ftf.margin_left = 0

        p1 = ftf.paragraphs[0]
        p1.text = f_tag
        p1.font.name = "Arial"
        p1.font.size = Pt(13)
        p1.font.bold = True
        p1.font.color.rgb = f_col
        p1.space_after = Pt(6)

        p2 = ftf.add_paragraph()
        p2.text = f_head
        p2.font.name = "Arial"
        p2.font.size = Pt(18)
        p2.font.bold = True
        p2.font.color.rgb = TEXT_WHITE
        p2.space_after = Pt(14)

        for pt in f_pts:
            fpt = ftf.add_paragraph()
            fpt.text = f"•  {pt}"
            fpt.font.name = "Arial"
            fpt.font.size = Pt(12)
            fpt.font.color.rgb = TEXT_LIGHT
            fpt.space_after = Pt(10)

    add_footer(s9, 9)

    # ==========================================
    # SLIDE 10: Future Scope
    # ==========================================
    s10 = prs.slides.add_slide(blank_layout)
    apply_bg(s10)
    add_header(s10, "9. FUTURE SCOPE & ROADMAP", "Scaling from Hackathon MVP to National Transparency Infrastructure",
               "Strategic expansion across real-time consumer warnings, regulatory APIs, and global jurisdictions.")

    roadmap_items = [
        ("Phase 1: Real-Time Consumer Extension",
         "Live Browser Co-Pilot",
         [
             "Chrome/Firefox extension auditing checkout funnels in the background while users shop.",
             "Instant warning badges appear when a hidden fee or pre-ticked add-on is detected.",
             "One-click 'Report to Checkout Radar' crowdsourced fee tracking."
         ], CYAN_ACCENT),
        ("Phase 2: National Consumer Helpline Integration",
         "Direct Regulatory API Pipe",
         [
             "Direct integration with NCH (National Consumer Helpline) and e-Daakhil consumer court APIs.",
             "Automated grievance filing with digitally signed, SHA-256 hashed evidence bundles.",
             "Enables consumer organizations to file class-action transparency complaints."
         ], BLUE_ACCENT),
        ("Phase 3: Cross-Border Multi-Region Audits",
         "Global E-Commerce Expansion",
         [
             "Deploy residential browser proxies across 7 jurisdictions (US, UK, EU, Canada, Australia, Japan, India).",
             "Audit geographic price discrimination, currency conversion drip fees, and international shipping surges.",
             "Compliance engine mapped to EU Digital Services Act (DSA) and US FTC Dark Pattern guidelines."
         ], PURPLE),
    ]

    for i, (r_tag, r_head, r_pts, r_col) in enumerate(roadmap_items):
        cx = Inches(0.8) + i * (col_w3 + col_gap)
        add_card(s10, cx, c_y, col_w3, c_h)

        rbox = s10.shapes.add_textbox(cx + Inches(0.25), c_y + Inches(0.25), col_w3 - Inches(0.5), c_h - Inches(0.5))
        rtf = rbox.text_frame
        rtf.word_wrap = True
        rtf.margin_top = rtf.margin_left = 0

        p1 = rtf.paragraphs[0]
        p1.text = r_tag
        p1.font.name = "Arial"
        p1.font.size = Pt(13)
        p1.font.bold = True
        p1.font.color.rgb = r_col
        p1.space_after = Pt(6)

        p2 = rtf.add_paragraph()
        p2.text = r_head
        p2.font.name = "Arial"
        p2.font.size = Pt(18)
        p2.font.bold = True
        p2.font.color.rgb = TEXT_WHITE
        p2.space_after = Pt(14)

        for pt in r_pts:
            rpt = rtf.add_paragraph()
            rpt.text = f"•  {pt}"
            rpt.font.name = "Arial"
            rpt.font.size = Pt(12)
            rpt.font.color.rgb = TEXT_LIGHT
            rpt.space_after = Pt(10)

    add_footer(s10, 10)

    # Save presentation
    output_path = Path("docs/pitch/Checkout_Radar_AZINHACK_2026.pptx")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    prs.save(str(output_path))
    print(f"Presentation saved successfully to: {output_path}")

if __name__ == "__main__":
    create_presentation()
