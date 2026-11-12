// Each people gets its own hue, spread round the colour wheel so neighbours in
// the list differ clearly. There can be dozens, so colour never stands alone.
export function peopleColour(id: number): number {
  // Greens are left out: most of the land is green, and a border has to stand out on it.
  const hue = ((170 + ((id * 137.508) % 270)) % 360) / 60;
  const chroma = 0.62;
  const x = chroma * (1 - Math.abs((hue % 2) - 1));
  const [r, g, b] = [[chroma, x, 0], [x, chroma, 0], [0, chroma, x], [0, x, chroma], [x, 0, chroma], [chroma, 0, x]][Math.floor(hue) % 6];
  const lift = 0.32;
  return (Math.round((r + lift) * 255) << 16) | (Math.round((g + lift) * 255) << 8) | Math.round((b + lift) * 255);
}

export function peopleCss(id: number): string {
  return `#${peopleColour(id).toString(16).padStart(6, "0")}`;
}
