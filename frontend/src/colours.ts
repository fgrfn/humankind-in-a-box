// Every people gets a colour of its own. The first twelve come from a fixed set
// picked to be told apart easily, also on the green and brown land; after that
// hues are spread by the golden ratio. There can be dozens of peoples, so a
// colour never stands alone: the name is always written next to it.
const DISTINCT = [
  0xe0569f, // raspberry
  0x3fc4e6, // sky
  0xf28c38, // orange
  0x9b7bf2, // violet
  0xf2d34a, // yellow
  0xe8453c, // red
  0x4f7ff0, // blue
  0xf5a3c7, // pink
  0xd9d4c7, // bone
  0xb84fd6, // purple
  0xc98a52, // copper
  0x36d6c6, // turquoise
];

export function peopleColour(id: number): number {
  if (id >= 1 && id <= DISTINCT.length) return DISTINCT[id - 1];
  // Greens are left out: most of the land is green, and a border has to stand out on it.
  const turn = (id * 0.6180339887) % 1;
  const hue = ((170 + turn * 270) % 360) / 60;
  const chroma = 0.62;
  const x = chroma * (1 - Math.abs((hue % 2) - 1));
  const [r, g, b] = [[chroma, x, 0], [x, chroma, 0], [0, chroma, x], [0, x, chroma], [x, 0, chroma], [chroma, 0, x]][Math.floor(hue) % 6];
  const lift = id % 2 === 0 ? 0.32 : 0.22; // alternate lightness too
  return (Math.round((r + lift) * 255) << 16) | (Math.round((g + lift) * 255) << 8) | Math.round((b + lift) * 255);
}

export function peopleCss(id: number): string {
  return `#${peopleColour(id).toString(16).padStart(6, "0")}`;
}

// Chiefdoms are shown on their own, never together with peoples, so they use
// the same twelve colours. Chiefdoms founded close in time often lie side by
// side, so consecutive ones step five places through the set: red, copper,
// violet, bone, sky, blue, turquoise, yellow, purple, orange, pink, raspberry.
// After twelve the colours come round again; the name is written on the land.
export function realmColour(id: number): number {
  return DISTINCT[(Math.max(1, id) * 5) % DISTINCT.length];
}

// Faiths are shown alone too; they step seven places so neighbours differ.
export function faithColour(id: number): number {
  return DISTINCT[(Math.max(1, id) * 7 + 3) % DISTINCT.length];
}

export function faithCss(id: number): string {
  return `#${faithColour(id).toString(16).padStart(6, "0")}`;
}

export function realmCss(id: number): string {
  return `#${realmColour(id).toString(16).padStart(6, "0")}`;
}
