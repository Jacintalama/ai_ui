// src/data.js — flight catalog. Stable IDs (no Math.random at load).
export const airlines = [
  "Skylane", "Northwind", "Aegis Air", "Pacific Crest",
  "Lumen Atlantic", "Cirrus", "Helios", "Veridian",
];

export const cities = [
  { code: "JFK", label: "New York (JFK)" },
  { code: "LHR", label: "London (LHR)" },
  { code: "SFO", label: "San Francisco (SFO)" },
  { code: "NRT", label: "Tokyo (NRT)" },
  { code: "LAX", label: "Los Angeles (LAX)" },
  { code: "CDG", label: "Paris (CDG)" },
  { code: "ATL", label: "Atlanta (ATL)" },
  { code: "FCO", label: "Rome (FCO)" },
];

// Bucket departure times for the time-of-day filter.
const bucketize = (hour) =>
  hour < 6 ? "early" : hour < 12 ? "morning" : hour < 18 ? "afternoon" : "evening";

// 30 flights across 8 routes. Realistic prices ($420-$1840) + durations.
// Generate in code so this is paste-friendly while staying deterministic.
const routes = [
  ["JFK","LHR"], ["JFK","LHR"], ["JFK","LHR"], ["JFK","LHR"],
  ["SFO","NRT"], ["SFO","NRT"], ["SFO","NRT"],
  ["LAX","CDG"], ["LAX","CDG"], ["LAX","CDG"],
  ["ATL","FCO"], ["ATL","FCO"], ["ATL","FCO"],
  ["LHR","JFK"], ["LHR","JFK"], ["LHR","JFK"],
  ["NRT","SFO"], ["NRT","SFO"], ["NRT","SFO"],
  ["CDG","LAX"], ["CDG","LAX"],
  ["FCO","ATL"], ["FCO","ATL"],
  ["JFK","CDG"], ["JFK","CDG"],
  ["SFO","LHR"], ["SFO","LHR"],
  ["LAX","NRT"], ["LAX","NRT"], ["LAX","NRT"],
];

const seedPrices = [642, 589, 531, 728, 1240, 1180, 1395, 980, 1120, 875,
  812, 925, 760, 598, 642, 720, 1310, 1260, 1410, 1095, 1240,
  890, 940, 720, 810, 1180, 1245, 1530, 1610, 1480];
const seedStops = [0,0,1,1, 0,1,0, 1,0,1, 1,2,1, 0,1,0, 0,1,0, 0,1, 1,0, 1,0, 1,2, 0,1,2];
const seedDurations = [420,490,540,460, 660,720,640, 690,640,720, 600,720,580, 420,490,470, 720,780,640, 720,840, 600,540, 460,500, 690,750, 700,800,860];
const seedDepartHours = [8,11,14,19, 9,11,13, 7,15,21, 8,13,18, 10,14,20, 8,13,19, 11,17, 9,16, 7,16, 10,15, 12,18,22];

export const flights = routes.map(([origin, destination], i) => {
  const depHour = seedDepartHours[i];
  return {
    id: `flt-${String(i + 1).padStart(3, "0")}`,
    origin,
    destination,
    airline: airlines[i % airlines.length],
    price: seedPrices[i],
    stops: seedStops[i],
    duration: seedDurations[i],         // minutes
    departureHour: depHour,
    departureBucket: bucketize(depHour),
    departureLabel: `${String(depHour).padStart(2, "0")}:00`,
    arrivalLabel: `${String((depHour + Math.floor(seedDurations[i] / 60)) % 24).padStart(2, "0")}:${String(seedDurations[i] % 60).padStart(2, "0")}`,
    cabin: i % 5 === 0 ? "Business" : "Economy",
    baggage: i % 5 === 0 ? "2× 32kg checked" : "1× 23kg checked",
  };
}).sort((a, b) => a.price - b.price);
