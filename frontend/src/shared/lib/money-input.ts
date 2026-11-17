/** Display separators never enter the value submitted to the API. */
export function parseMoneyInput(text: string): string | null {
  const raw = text.replace(/[,\s]/g, "");
  if (!/^(?:\d+(?:\.\d{0,2})?|\.\d{0,2})?$/.test(raw)) return null;
  return (raw.startsWith(".") ? `0${raw}` : raw).replace(/^0+(?=\d)/, "");
}

export function formatMoneyInput(raw: string): string {
  const [whole, fraction] = raw.split(".");
  const grouped = whole.replace(/\B(?=(\d{3})+(?!\d))/g, ",");
  return fraction === undefined ? grouped : `${grouped}.${fraction}`;
}

export function moneyCaret(
  display: string,
  significantCharacters: number,
): number {
  if (!significantCharacters) return 0;
  let count = 0;
  for (let index = 0; index < display.length; index++) {
    if (display[index] !== ",") count++;
    if (count === significantCharacters) return index + 1;
  }
  return display.length;
}
