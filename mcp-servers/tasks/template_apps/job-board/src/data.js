// src/data.js — job catalog, stable IDs.

const companies = [
  ["Northwind Logistics", "Logistics", "Boston, MA"],
  ["Lumen Health", "Healthcare", "Austin, TX"],
  ["Halftone Studio", "Design", "Remote"],
  ["Cirrus Cloud", "DevOps", "San Francisco, CA"],
  ["Aegis Security", "Cybersecurity", "Remote"],
  ["Pacific Crest Bank", "Fintech", "Seattle, WA"],
  ["Skylane Travel", "Travel-tech", "Remote"],
  ["Verde Wellness", "Consumer", "Brooklyn, NY"],
  ["Helios Energy", "Climate-tech", "Denver, CO"],
  ["Veridian Robotics", "Robotics", "Pittsburgh, PA"],
  ["DevCon Berlin", "Events", "Berlin, DE"],
  ["Salt & Pan Media", "Media", "Remote"],
];

const roleSeeds = [
  ["Senior Frontend Engineer", "Engineering", "senior", 145, 180, "remote"],
  ["Staff Backend Engineer", "Engineering", "staff+", 175, 230, "hybrid"],
  ["Product Designer", "Design", "mid", 110, 140, "remote"],
  ["Senior Product Manager", "PM", "senior", 150, 200, "hybrid"],
  ["Data Engineer", "Data", "mid", 130, 165, "remote"],
  ["Marketing Lead", "Marketing", "senior", 120, 155, "hybrid"],
  ["DevOps Engineer", "Engineering", "mid", 125, 160, "remote"],
  ["Junior Frontend Developer", "Engineering", "junior", 75, 105, "onsite"],
  ["Senior UX Researcher", "Design", "senior", 130, 170, "remote"],
  ["Engineering Manager", "Engineering", "staff+", 195, 250, "hybrid"],
  ["Content Strategist", "Marketing", "mid", 90, 120, "remote"],
  ["Machine Learning Engineer", "Data", "senior", 165, 220, "hybrid"],
];

// 60 jobs = 12 companies x 5 roles each (rotated through roleSeeds).
export const jobs = (() => {
  const out = [];
  let id = 1;
  for (let c = 0; c < companies.length; c++) {
    for (let r = 0; r < 5; r++) {
      const role = roleSeeds[(c + r) % roleSeeds.length];
      const [comp, industry, baseLocation] = companies[c];
      out.push({
        id: `job-${String(id++).padStart(3, "0")}`,
        title: role[0],
        company: comp,
        industry,
        location: role[5] === "remote" ? "Remote" : baseLocation,
        remoteMode: role[5],
        roleFamily: role[1],
        seniority: role[2],
        salaryMin: role[3] * 1000,
        salaryMax: role[4] * 1000,
        postedDaysAgo: ((c * 5 + r) % 14) + 1,
        // DiceBear initials avatar
        logo: `https://api.dicebear.com/7.x/initials/svg?seed=${encodeURIComponent(comp)}&backgroundColor=2563eb`,
        description: [
          `Join ${comp} as a ${role[0]}.`,
          `Reporting to the Head of ${role[1]}, you'll own the roadmap for our ${industry.toLowerCase()} platform — shipping product to customers across our core markets.`,
          `Requirements: 5+ years of experience, strong fundamentals, ability to mentor. Familiarity with our stack (TypeScript, Python, Postgres) is a plus.`,
          `We offer: competitive comp ($${role[3]}k-$${role[4]}k), full benefits, ${role[5]} working, generous PTO, learning budget.`,
        ].join("\n\n"),
      });
    }
  }
  return out.sort((a, b) => a.postedDaysAgo - b.postedDaysAgo);
})();

export const companiesList = companies.map(([name]) => name);
export const roleFamilies = ["Engineering", "Design", "PM", "Marketing", "Data"];
