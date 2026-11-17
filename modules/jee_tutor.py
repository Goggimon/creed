# modules/jee_tutor.py

import json
import re
import httpx
from config.settings import config

# Curated 5-Year (2022-2026) JEE Main PYQ Weightage & High-ROI Vault
PYQ_VAULT = [
    {
        "subject": "Physics",
        "chapter": "Modern Physics (Dual Nature, Atoms, Nuclei)",
        "weightage": "10.8%",
        "avg_qs": "2.7 / paper",
        "roi": "Must Do (High ROI)",
        "key_patterns": "Photoelectric threshold & stopping potential, de Broglie wavelength ratios, Bohr radius/energy transitions, binding energy & Q-value.",
    },
    {
        "subject": "Physics",
        "chapter": "Current Electricity",
        "weightage": "9.2%",
        "avg_qs": "2.3 / paper",
        "roi": "Must Do (High ROI)",
        "key_patterns": "Equivalent resistance symmetry, Wheatstone/meter bridge, RC transient steady-state, potentiometer & galvanometer conversion.",
    },
    {
        "subject": "Physics",
        "chapter": "Electrostatics & Capacitance",
        "weightage": "8.4%",
        "avg_qs": "2.1 / paper",
        "roi": "High ROI",
        "key_patterns": "Gauss law shells/cylinders, dipole torque & potential, dielectric slab insertion (battery connected vs disconnected).",
    },
    {
        "subject": "Physics",
        "chapter": "Ray & Wave Optics",
        "weightage": "7.6%",
        "avg_qs": "1.9 / paper",
        "roi": "High ROI",
        "key_patterns": "Lens maker + silvering, prism minimum deviation, YDSE fringe shift with thin glass slab, Brewster angle.",
    },
    {
        "subject": "Physics",
        "chapter": "Thermodynamics & KTG",
        "weightage": "7.2%",
        "avg_qs": "1.8 / paper",
        "roi": "Must Do (High ROI)",
        "key_patterns": "v_rms / v_avg ratios, Cp/Cv of gas mixtures, Carnot efficiency, isothermal vs adiabatic work & PV indicator diagrams.",
    },
    {
        "subject": "Physics",
        "chapter": "Semiconductors & Logic Gates",
        "weightage": "4.8%",
        "avg_qs": "1.2 / paper",
        "roi": "Must Do (Easy 4 Marks)",
        "key_patterns": "Zener diode voltage regulation, forward/reverse bias diode circuits, NAND/NOR universal gate truth tables.",
    },
    {
        "subject": "Chemistry",
        "chapter": "Coordination Compounds",
        "weightage": "8.8%",
        "avg_qs": "2.2 / paper",
        "roi": "Must Do (High ROI)",
        "key_patterns": "CFT splitting & CFSE, magnetic moment (spin-only), IUPAC naming, geometrical/optical isomerism in octahedral complexes.",
    },
    {
        "subject": "Chemistry",
        "chapter": "Chemical Bonding & Molecular Structure",
        "weightage": "8.0%",
        "avg_qs": "2.0 / paper",
        "roi": "Must Do (High ROI)",
        "key_patterns": "MOT bond order & paramagnetism (O2, N2, B2, C2), VSEPR shapes & lone pairs, dipole moment, H-bonding.",
    },
    {
        "subject": "Chemistry",
        "chapter": "General Organic Chemistry (GOC)",
        "weightage": "8.4%",
        "avg_qs": "2.1 / paper",
        "roi": "Must Do (Foundation)",
        "key_patterns": "Acidic/basic strength (ortho effect, SIR), carbocation rearrangement, aromaticity (Hückel 4n+2), resonance stability.",
    },
    {
        "subject": "Chemistry",
        "chapter": "Electrochemistry & Chemical Kinetics",
        "weightage": "9.6%",
        "avg_qs": "2.4 / paper",
        "roi": "High ROI",
        "key_patterns": "Nernst equation, Kohlrausch molar conductivity, first-order half-life & Arrhenius activation energy plots.",
    },
    {
        "subject": "Chemistry",
        "chapter": "Aldehydes, Ketones & Biomolecules",
        "weightage": "7.6%",
        "avg_qs": "1.9 / paper",
        "roi": "High ROI",
        "key_patterns": "Aldol/Cannizzaro cross-products, Tollens/Fehling tests, glucose structure & zwitterion pI.",
    },
    {
        "subject": "Mathematics",
        "chapter": "Vectors & 3D Geometry",
        "weightage": "12.4%",
        "avg_qs": "3.1 / paper",
        "roi": "Must Do (Highest ROI)",
        "key_patterns": "Shortest distance between skew lines, image/foot of perpendicular on line/plane, scalar & vector triple products.",
    },
    {
        "subject": "Mathematics",
        "chapter": "Matrices & Determinants",
        "weightage": "8.0%",
        "avg_qs": "2.0 / paper",
        "roi": "Must Do (High ROI)",
        "key_patterns": "System of linear equations (Cramer's consistency), adj(A) properties, Cayley-Hamilton & trace.",
    },
    {
        "subject": "Mathematics",
        "chapter": "Sequences & Series + Binomial",
        "weightage": "8.4%",
        "avg_qs": "2.1 / paper",
        "roi": "High ROI",
        "key_patterns": "Telescoping sigma sums, AM-GM inequality, general term & remainder theorem in binomial expansion.",
    },
    {
        "subject": "Mathematics",
        "chapter": "Definite Integration & Area",
        "weightage": "8.8%",
        "avg_qs": "2.2 / paper",
        "roi": "High ROI",
        "key_patterns": "King's property (a+b-x), Leibniz differentiation under integral sign, area bounded by parabola & line.",
    },
    {
        "subject": "Mathematics",
        "chapter": "Differential Equations",
        "weightage": "6.4%",
        "avg_qs": "1.6 / paper",
        "roi": "Must Do (High ROI)",
        "key_patterns": "Linear first-order dy/dx + Py = Q (integrating factor), Bernoulli & homogeneous substitution.",
    },
]

# Pre-loaded verified formulas, sign conventions & JEE traps for instant local RAG
JEE_KNOWLEDGE_BASE = [
    {
        "tags": "arrhenius kinetics rate constant activation energy slope half life first order",
        "title": "Chemical Kinetics & Arrhenius Equation",
        "content": (
            "k = A e^(-Ea / RT); ln(k2/k1) = (Ea/R) * (1/T1 - 1/T2). "
            "Plot of ln(k) vs 1/T has slope = -Ea/R; log10(k) vs 1/T has slope = -Ea/(2.303 R). "
            "First-order t_1/2 = 0.693/k (independent of [A]0); t_99.9% ≈ 10 * t_1/2."
        ),
    },
    {
        "tags": "electrochemistry nernst kohlrausch emf gibbs cell potential",
        "title": "Electrochemistry & Nernst Equation",
        "content": (
            "At 298 K: E_cell = E0_cell - (0.0591 / n) * log10(Q). ΔG° = -n F E0_cell = -2.303 R T log10(K_eq). "
            "Trap: E0 is an intensive property—never multiply E0 when doubling a half-reaction; add ΔG° instead."
        ),
    },
    {
        "tags": "mot molecular orbital bond order paramagnetic o2 n2 b2 c2 vsepr",
        "title": "Chemical Bonding & MOT",
        "content": (
            "For <=14 electrons (B2, C2, N2): sigma2p_z is ABOVE pi2p_x = pi2p_y. B2 (10e, BO=1) is paramagnetic! "
            "For >14 electrons (O2, F2): sigma2p_z is BELOW pi2p_x = pi2p_y. O2 (16e, BO=2) has 2 unpaired e- in pi*."
        ),
    },
    {
        "tags": "coordination cfse crystal field isomerism magnetic moment spin",
        "title": "Coordination Compounds",
        "content": (
            "μ = sqrt(n(n+2)) BM. Strong-field ligands (CN-, CO, en, NH3 with Co3+) pair electrons (low spin). "
            "CFSE(octahedral) = (-0.4 t2g + 0.6 eg) Δo + pairing energy. [Ma2b2c2] has 5 geometrical isomers (1 optically active pair -> 6 stereoisomers)."
        ),
    },
    {
        "tags": "goc acidic basic ortho effect sir resonance aromaticity carbocation",
        "title": "GOC Traps (Ortho Effect & SIR)",
        "content": (
            "Ortho-substituted benzoic acids are stronger acids than meta/para regardless of +M/-I group (SIR twists -COOH out of plane). "
            "In aqueous amine basicity: Et2NH > Et3N > EtNH2 > NH3; Me2NH > MeNH2 > Me3N > NH3."
        ),
    },
    {
        "tags": "modern physics photoelectric bohr de broglie binding energy q value",
        "title": "Modern Physics Formulas",
        "content": (
            "eV0 = hc/λ - φ0 (hc ≈ 1240 eV·nm). de Broglie: λ = h / sqrt(2 m q V). "
            "Bohr: r_n = 0.529 n^2/Z Å, E_n = -13.6 Z^2/n^2 eV. Q-value = BE(products) - BE(reactants)."
        ),
    },
    {
        "tags": "ray optics lens mirror magnification silvered prism ydse interference",
        "title": "Ray & Wave Optics",
        "content": (
            "New Cartesian sign convention: incident ray direction is +ve. Lens: 1/v - 1/u = 1/f; Mirror: 1/v + 1/u = 1/f. "
            "Silvered lens: 1/F_eq = 2/f_lens - 1/f_mirror (watch signs!). YDSE slab shift: Δy = (μ - 1) t D / d."
        ),
    },
    {
        "tags": "thermodynamics carnot adiabatic isothermal work sign convention ktg rms",
        "title": "Thermodynamics Sign Trap & KTG",
        "content": (
            "Physics: ΔQ = ΔU + ΔW (W = ∫P dV, +ve for expansion). Chemistry: ΔU = q + w (w = -∫P_ext dV, -ve for expansion). "
            "Adiabatic work: W = (P1V1 - P2V2)/(γ - 1). v_rms = sqrt(3RT/M), v_avg = sqrt(8RT/πM), v_mp = sqrt(2RT/M)."
        ),
    },
    {
        "tags": "current electricity wheatstone rc circuit potentiometer galvanometer",
        "title": "Current Electricity & RC Transients",
        "content": (
            "At t=0 (uncharged C): capacitor acts as a short circuit (0 V). At t→∞ (steady state): capacitor acts as open circuit (0 A). "
            "Galvanometer to Ammeter: small shunt S = I_g G / (I - I_g) in parallel. To Voltmeter: high R = (V/I_g) - G in series."
        ),
    },
    {
        "tags": "electrostatics capacitance dielectric battery connected disconnected gauss",
        "title": "Capacitors & Dielectrics",
        "content": (
            "Battery connected (V const): C -> KC, Q -> KQ, E const, U -> KU. "
            "Battery disconnected (Q const): C -> KC, V -> V/K, E -> E/K, U -> U/K."
        ),
    },
    {
        "tags": "semiconductor zener diode logic gate nand nor",
        "title": "Semiconductors & Zener Regulation",
        "content": (
            "Zener check: first compute open-circuit V_th across Zener without Zener. If V_th < V_z, Zener is OFF (open); if V_th >= V_z, Zener clamps at V_z and I_z = I_R - I_L."
        ),
    },
    {
        "tags": "vectors 3d skew lines shortest distance foot perpendicular plane",
        "title": "Vectors & 3D Geometry",
        "content": (
            "Shortest distance between skew lines r = a1 + λb1 and r = a2 + μb2: d = |(a2 - a1) · (b1 × b2)| / |b1 × b2|. "
            "Foot of perpendicular (x1,y1,z1) on ax+by+cz+d=0: (x-x1)/a = (y-y1)/b = (z-z1)/c = -(ax1+by1+cz1+d)/(a^2+b^2+c^2) (double for image!)."
        ),
    },
    {
        "tags": "definite integration king property leibniz area",
        "title": "Definite Integration & Leibniz Rule",
        "content": (
            "King's Property: ∫_a^b f(x)dx = ∫_a^b f(a+b-x)dx. "
            "Leibniz: d/dx ∫_{g(x)}^{h(x)} f(t)dt = f(h(x))h'(x) - f(g(x))g'(x)."
        ),
    },
]

# Pre-built 0ms SVG diagram templates
SVG_TEMPLATES = {
    "Incline FBD": (
        "<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 460 260'>"
        "<rect width='460' height='260' fill='#101114'/>"
        "<polygon points='60,220 380,220 380,90' fill='#181A20' stroke='#60A5FA' stroke-width='2'/>"
        "<text x='115' y='210' fill='#9CA3AF' font-size='13'>θ</text>"
        "<g transform='translate(245,142) rotate(-22)'>"
        "<rect x='-26' y='-18' width='52' height='36' rx='4' fill='#1E2430' stroke='#F3F4F6' stroke-width='2'/>"
        "<text x='-7' y='5' fill='#F3F4F6' font-size='13'>m</text>"
        "<line x1='0' y1='-18' x2='0' y2='-66' stroke='#34D399' stroke-width='2.5'/>"
        "<text x='6' y='-55' fill='#34D399' font-size='12'>N = mg cosθ</text>"
        "<line x1='-26' y1='0' x2='-85' y2='0' stroke='#FBBF24' stroke-width='2.5'/>"
        "<text x='-115' y='-8' fill='#FBBF24' font-size='12'>mg sinθ</text>"
        "<line x1='26' y1='0' x2='75' y2='0' stroke='#F87171' stroke-width='2.5'/>"
        "<text x='48' y='-8' fill='#F87171' font-size='12'>f_s</text>"
        "</g>"
        "<line x1='245' y1='142' x2='245' y2='215' stroke='#60A5FA' stroke-width='2.5'/>"
        "<text x='252' y='208' fill='#60A5FA' font-size='12'>mg</text>"
        "</svg>"
    ),
    "Convex Lens Ray": (
        "<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 460 260'>"
        "<rect width='460' height='260' fill='#101114'/>"
        "<line x1='20' y1='130' x2='440' y2='130' stroke='#52525B' stroke-width='1.5' stroke-dasharray='5,4'/>"
        "<path d='M230,35 Q252,130 230,225 Q208,130 230,35 Z' fill='rgba(96,165,250,0.16)' stroke='#60A5FA' stroke-width='2'/>"
        "<circle cx='150' cy='130' r='3' fill='#FBBF24'/><text x='145' y='148' fill='#FBBF24' font-size='12'>F1</text>"
        "<circle cx='310' cy='130' r='3' fill='#FBBF24'/><text x='305' y='148' fill='#FBBF24' font-size='12'>F2</text>"
        "<line x1='95' y1='130' x2='95' y2='70' stroke='#34D399' stroke-width='3'/>"
        "<line x1='95' y1='70' x2='230' y2='70' stroke='#F3F4F6' stroke-width='1.8'/>"
        "<line x1='230' y1='70' x2='390' y2='190' stroke='#F3F4F6' stroke-width='1.8'/>"
        "<line x1='95' y1='70' x2='390' y2='190' stroke='#93C5FD' stroke-width='1.8'/>"
        "<line x1='355' y1='130' x2='355' y2='165' stroke='#F87171' stroke-width='3'/>"
        "<text x='340' y='182' fill='#F87171' font-size='12'>Image</text>"
        "</svg>"
    ),
    "Wheatstone Bridge": (
        "<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 460 260'>"
        "<rect width='460' height='260' fill='#101114'/>"
        "<line x1='90' y1='130' x2='230' y2='45' stroke='#60A5FA' stroke-width='2.5'/>"
        "<line x1='230' y1='45' x2='370' y2='130' stroke='#60A5FA' stroke-width='2.5'/>"
        "<line x1='90' y1='130' x2='230' y2='215' stroke='#60A5FA' stroke-width='2.5'/>"
        "<line x1='230' y1='215' x2='370' y2='130' stroke='#60A5FA' stroke-width='2.5'/>"
        "<line x1='230' y1='45' x2='230' y2='215' stroke='#34D399' stroke-width='2'/>"
        "<circle cx='230' cy='130' r='16' fill='#181A20' stroke='#34D399' stroke-width='2'/>"
        "<text x='224' y='135' fill='#34D399' font-size='14'>G</text>"
        "<text x='135' y='78' fill='#F3F4F6' font-size='13'>R1</text>"
        "<text x='305' y='78' fill='#F3F4F6' font-size='13'>R2</text>"
        "<text x='135' y='192' fill='#F3F4F6' font-size='13'>R3</text>"
        "<text x='305' y='192' fill='#F3F4F6' font-size='13'>R4</text>"
        "<text x='140' y='246' fill='#FBBF24' font-size='12'>Balanced when R1/R2 = R3/R4</text>"
        "</svg>"
    ),
    "Carnot PV": (
        "<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 460 260'>"
        "<rect width='460' height='260' fill='#101114'/>"
        "<line x1='65' y1='30' x2='65' y2='220' stroke='#9CA3AF' stroke-width='2'/>"
        "<line x1='65' y1='220' x2='405' y2='220' stroke='#9CA3AF' stroke-width='2'/>"
        "<text x='42' y='40' fill='#9CA3AF' font-size='13'>P</text>"
        "<text x='400' y='238' fill='#9CA3AF' font-size='13'>V</text>"
        "<path d='M120,65 Q200,85 270,105' fill='none' stroke='#F87171' stroke-width='2.5'/>"
        "<path d='M270,105 Q315,155 345,180' fill='none' stroke='#60A5FA' stroke-width='2.5'/>"
        "<path d='M345,180 Q245,165 180,140' fill='none' stroke='#34D399' stroke-width='2.5'/>"
        "<path d='M180,140 Q145,95 120,65' fill='none' stroke='#60A5FA' stroke-width='2.5'/>"
        "<text x='190' y='70' fill='#F87171' font-size='11'>Isothermal T_H (Q_in)</text>"
        "<text x='235' y='186' fill='#34D399' font-size='11'>Isothermal T_C (Q_out)</text>"
        "<text x='145' y='245' fill='#FBBF24' font-size='12'>η = 1 - T_C / T_H</text>"
        "</svg>"
    ),
    "YDSE": (
        "<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 460 260'>"
        "<rect width='460' height='260' fill='#101114'/>"
        "<line x1='110' y1='35' x2='110' y2='95' stroke='#9CA3AF' stroke-width='4'/>"
        "<line x1='110' y1='108' x2='110' y2='152' stroke='#9CA3AF' stroke-width='4'/>"
        "<line x1='110' y1='165' x2='110' y2='225' stroke='#9CA3AF' stroke-width='4'/>"
        "<line x1='380' y1='30' x2='380' y2='230' stroke='#60A5FA' stroke-width='3'/>"
        "<line x1='110' y1='101' x2='380' y2='75' stroke='#34D399' stroke-width='1.8'/>"
        "<line x1='110' y1='158' x2='380' y2='75' stroke='#FBBF24' stroke-width='1.8'/>"
        "<text x='80' y='105' fill='#34D399' font-size='12'>S1</text>"
        "<text x='80' y='162' fill='#FBBF24' font-size='12'>S2</text>"
        "<text x='220' y='246' fill='#F3F4F6' font-size='12'>β = λD / d   •   Δy_slab = (μ-1)tD/d</text>"
        "</svg>"
    ),
    "Zener Diode": (
        "<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 460 260'>"
        "<rect width='460' height='260' fill='#101114'/>"
        "<line x1='60' y1='70' x2='380' y2='70' stroke='#60A5FA' stroke-width='2.5'/>"
        "<line x1='60' y1='190' x2='380' y2='190' stroke='#60A5FA' stroke-width='2.5'/>"
        "<rect x='130' y='58' width='60' height='24' fill='#181A20' stroke='#F3F4F6' stroke-width='2'/>"
        "<text x='150' y='74' fill='#F3F4F6' font-size='12'>R_s</text>"
        "<line x1='240' y1='70' x2='240' y2='190' stroke='#FBBF24' stroke-width='2'/>"
        "<polygon points='226,145 254,145 240,115' fill='#FBBF24'/>"
        "<line x1='224' y1='115' x2='256' y2='115' stroke='#FBBF24' stroke-width='2.5'/>"
        "<rect x='330' y='105' width='26' height='50' fill='#181A20' stroke='#34D399' stroke-width='2'/>"
        "<line x1='343' y1='70' x2='343' y2='105' stroke='#34D399' stroke-width='2'/>"
        "<line x1='343' y1='155' x2='343' y2='190' stroke='#34D399' stroke-width='2'/>"
        "<text x='364' y='134' fill='#34D399' font-size='12'>R_L</text>"
        "<text x='115' y='235' fill='#9CA3AF' font-size='12'>V_L = V_Z when V_th ≥ V_Z  •  I_s = I_Z + I_L</text>"
        "</svg>"
    ),
}


def retrieve_jee_context(query: str, limit: int = 3) -> str:
    """Fast 0ms local RAG over pre-loaded JEE formulas, traps, and 5-year PYQ patterns."""
    words = {w for w in re.findall(r"\b[a-z0-9_]{2,}\b", query.lower())}
    if not words:
        return ""
    scored = []
    for item in JEE_KNOWLEDGE_BASE:
        hay = (item["tags"] + " " + item["title"] + " " + item["content"]).lower()
        score = sum(2 if w in item["tags"] else 1 for w in words if w in hay)
        if score > 0:
            scored.append((score, f"- {item['title']}: {item['content']}"))
    for p in PYQ_VAULT:
        hay = (p["subject"] + " " + p["chapter"] + " " + p["key_patterns"]).lower()
        score = sum(1 for w in words if w in hay)
        if score >= 2:
            scored.append((score, f"- PYQ Vault ({p['chapter']}, {p['weightage']}): {p['key_patterns']}"))
    scored.sort(reverse=True, key=lambda x: x[0])
    return "\n".join(text for _, text in scored[:limit])


def build_jee_system_prompt(model_name: str) -> dict:
    return {
        "role": "system",
        "content": (
            f"You are CREED JEE Tutor running on '{model_name}' locally via Ollama, helping a Class 12 student targeting JEE Main 2027 & Advanced (ECE, 181/300 baseline). "
            "Solve Physics, Chemistry, and Mathematics problems clearly and concisely: state the core formula, show step-by-step math in LaTeX ($...$ or $$...$$), check units/dimensions, and flag common JEE traps. "
            "When a diagram helps, output a clean ```svg ... ``` block (viewBox='0 0 460 260', dark #101114 background, crisp #F3F4F6 / #60A5FA / #34D399 / #FBBF24 strokes)."
        ),
    }


def pick_reasoning_model(installed_names: list[str]) -> str:
    """Pick the configured JEE reasoning model if installed, else the fastest strong local model (avoiding 14b swap unless selected)."""
    preferred = [
        config.jee_tutor_model,
        "qwen3:8b",
        "deepseek-r1:8b",
        "qwen2.5-coder:7b",
        "llama3.1:8b",
        "gemma2:9b",
        "qwen2.5:14b",
        config.ollama_model,
    ]
    for candidate in preferred:
        if not candidate:
            continue
        if any(candidate == n or candidate in n for n in installed_names):
            return next(n for n in installed_names if candidate == n or candidate in n)
    return installed_names[0] if installed_names else config.ollama_model


async def generate_jee_quiz(
    subject: str,
    chapter: str,
    difficulty: str,
    count: int,
    model_name: str,
) -> list[dict]:
    rag = retrieve_jee_context(f"{subject} {chapter}", limit=2)
    prompt = (
        f"Generate exactly {count} original {difficulty}-level multiple-choice questions "
        f"on {subject}" + (f" ({chapter})" if chapter else "") + ".\n"
        + (f"Reference formulas:\n{rag}\n" if rag else "")
        + "Return ONLY valid JSON: a list of objects with keys:\n"
        '  "question": string,\n'
        '  "options": [4 short strings],\n'
        '  "answer_index": integer 0-3,\n'
        '  "explanation": concise step-by-step solution string.\n'
        "No markdown fences, no commentary—JSON array only."
    )
    payload = {
        "model": model_name,
        "messages": [
            {"role": "system", "content": "You output strict, valid JSON arrays of JEE MCQ questions."},
            {"role": "user", "content": prompt},
        ],
        "stream": False,
        "keep_alive": "15m",
        "options": {"num_ctx": 4096, "temperature": 0.25},
    }
    async with httpx.AsyncClient(timeout=90.0) as client:
        resp = await client.post(config.ollama_endpoint, json=payload)
        resp.raise_for_status()
        raw = resp.json().get("message", {}).get("content", "").strip()

    start = raw.find("[")
    end = raw.rfind("]")
    if start != -1 and end != -1:
        raw = raw[start : end + 1]
    data = json.loads(raw)
    if not isinstance(data, list):
        raise ValueError("Model did not return a JSON list.")
    return data[:count]
