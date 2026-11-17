from pathlib import Path

AGENT_DIR = Path(__file__).parent


def skill_body(name):
    return (AGENT_DIR / "skills" / name / "SKILL.md").read_text().split("\n---\n", 1)[1].strip()


COMMUNICATION_SKILL = skill_body("comunicacion-cliente")
HUMAN_COMMUNICATION_SKILL = skill_body("comunicacion-humana")
INSTRUCTIONS = (
    (AGENT_DIR / "instructions" / "sales.md").read_text()
    + "\n\nSkills obligatorias para toda comunicación con el cliente, aplica ambas siempre:\n"
    + COMMUNICATION_SKILL
    + "\n\n"
    + HUMAN_COMMUNICATION_SKILL
)
CONVERSATION_PROTOCOL = (AGENT_DIR / "instructions" / "turn.md").read_text()
