# modules/jee_tutor.py

import json
import httpx
from config.settings import config

# Curated 5-Year (2022-2026) JEE Main PYQ Weightage & High-ROI Vault
PYQ_VAULT = [
    # Physics
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
    # Chemistry
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
    # Mathematics
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


def build_jee_system_prompt(model_name: str) -> dict:
    return {
        "role": "system",
        "content": (
            f"You are CREED JEE Tutor running on '{model_name}' locally via Ollama. "
            "You are an elite JEE Main & JEE Advanced Physics, Chemistry, and Mathematics mentor. "
            "Always solve problems step-by-step, show key formulas, check units/dimensions, and call out common JEE exam traps. "
            "Whenever a diagram, free-body diagram, circuit, ray diagram, or graph helps explain the problem, "
            "output a clean self-contained ```svg ... ``` block (dark background #0D0E12, crisp #ECEEF2 labels, #6EA8FE / #34D399 / #FBBF24 strokes, viewBox='0 0 460 260') "
            "so the CREED GUI renders it visually alongside your explanation."
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
    prompt = (
        f"Generate exactly {count} original {difficulty}-level multiple-choice questions "
        f"on {subject}" + (f" ({chapter})" if chapter else "") + ".\n"
        "Return ONLY valid JSON: a list of objects with keys:\n"
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
