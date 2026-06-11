// src/data.js — film catalog with showtimes + per-showtime seat occupancy.

// Stable Unsplash photo IDs that look like film stills / cinema imagery.
const posterIds = [
  "1489599849927-2ee91cede3ba", "1502136969935-8d8eef54d77b",
  "1517604931442-7e0c8ed2963c", "1485846234645-a62644f84728",
  "1542204165-65bf26472b9b", "1478720568477-152d9b164e26",
  "1543536448-d209d2d13a1c", "1554080353-a576cf803bda",
  "1499415479124-43c32433a620", "1536440136628-849c177e76a1",
  "1485095329183-d0797cdc5676", "1518929458119-e5bf444c30f4",
];

const filmSeeds = [
  ["Dune Pt 2",          "PG-13", "Sci-Fi",         166, "Paul Atreides unites with Chani and the Fremen."],
  ["The Crow",           "R",     "Action",          110, "A musician resurrected to avenge his murder."],
  ["Argylle",            "PG-13", "Action / Comedy", 139, "A reclusive spy novelist becomes entangled in real espionage."],
  ["Madame Web",         "PG-13", "Action",          116, "A clairvoyant New York paramedic unlocks her powers."],
  ["Drive-Away Dolls",   "R",     "Comedy",           84, "Two friends embark on a wild road trip."],
  ["Ordinary Angels",    "PG",    "Drama",            116, "A small-town hairdresser rallies her community."],
  ["Bob Marley: One Love","PG-13","Biopic",           107, "The story of the music icon."],
  ["Wonka",              "PG",    "Family",           116, "A young Willy Wonka begins his chocolate adventure."],
  ["Migration",          "PG",    "Animation",         92, "A duck family on their first migration."],
  ["The Beekeeper",      "R",     "Action",           105, "A man's quest for vengeance takes a national turn."],
  ["Anyone But You",     "R",     "Comedy",           103, "Two enemies fake-date at a wedding in Australia."],
  ["The Iron Claw",      "R",     "Drama",            132, "The rise and fall of the Von Erich wrestling family."],
];

export const films = filmSeeds.map(([title, rating, genre, runtime, synopsis], i) => ({
  id: `film-${String(i + 1).padStart(2, "0")}`,
  title,
  rating,
  genre,
  runtime,
  synopsis,
  poster: `https://images.unsplash.com/photo-${posterIds[i]}?w=600&q=80&auto=format`,
}));

export const theaters = [
  { id: "th-1", name: "Lumen Downtown",  address: "1200 Market St" },
  { id: "th-2", name: "Lumen Westside",  address: "4400 Sunset Blvd" },
  { id: "th-3", name: "Lumen Bayview",   address: "88 Bayview Ave" },
];

// Showtimes: per film × per theater × 5 times.
const showtimeSlots = ["12:30", "15:00", "17:30", "20:00", "22:30"];

export const SEAT_PRICE = 14;

function hash(str) {
  let h = 0;
  for (let i = 0; i < str.length; i++) h = ((h << 5) - h + str.charCodeAt(i)) | 0;
  return Math.abs(h);
}

// Pre-generate seat occupancy per showtime so it's stable across renders.
// 10 rows × 14 cols. Aisles = cols 4 & 9. ~30% randomly taken (deterministic by showtime hash).
export const showtimes = (() => {
  const out = [];
  films.forEach((f) => {
    theaters.forEach((t) => {
      showtimeSlots.forEach((slot) => {
        const id = `${f.id}-${t.id}-${slot.replace(":", "")}`;
        const seed = hash(id);
        const taken = new Set();
        for (let r = 0; r < 10; r++) {
          for (let c = 0; c < 14; c++) {
            if (c === 4 || c === 9) continue; // aisle columns
            if ((seed * (r + 1) * (c + 2)) % 10 < 3) taken.add(`${r}-${c}`);
          }
        }
        out.push({
          id,
          filmId: f.id,
          theaterId: t.id,
          slot,
          takenSeats: Array.from(taken),
        });
      });
    });
  });
  return out;
})();

export const genres = ["All", "Action", "Comedy", "Drama", "Sci-Fi", "Family", "Animation", "Biopic"];
