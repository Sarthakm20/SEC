/**
 * The page backdrop: a soft blue wave crossed by a guilloché band, the fine interlaced lines printed on
 * stock certificates, edged with microprint taken from a Form 10-K. The cover-page wording runs along the
 * upper edge and the report's Item list along the lower one. Cards laid over it simply cover part of the band.
 */

const W = 1700; // drawn at 1:1 on typical screens; wider screens scale it up without distortion
const H = 380;
const STEP = 10;

// the band's centreline: low on the left, rising towards the top-right corner
const centre = (x: number) => 268 - 205 * Math.pow(x / W, 1.35) + 10 * Math.sin(x / 230);

function curve(offset: (x: number) => number) {
  let d = "";
  for (let x = 0; x <= W; x += STEP) d += `${x === 0 ? "M" : "L"}${x} ${(centre(x) + offset(x)).toFixed(1)}`;
  return d;
}

// two families of strands with different wavelengths, phase-shifted, so they weave like guilloché
const STRANDS = [
  ...Array.from({ length: 7 }, (_, i) => curve((x) => 15 * Math.sin((2 * Math.PI * x) / 340 + (i * Math.PI) / 7))),
  ...Array.from({ length: 5 }, (_, i) => curve((x) => 11 * Math.sin((2 * Math.PI * x) / 520 + (i * 2 * Math.PI) / 5 + 1))),
];

const UPPER = curve(() => -27);
const LOWER = curve(() => 34);
const FILL = `${curve(() => 44)}L${W} 0L0 0Z`;

const COVER =
  "UNITED STATES SECURITIES AND EXCHANGE COMMISSION   Washington, D.C. 20549   FORM 10-K   ANNUAL REPORT PURSUANT TO SECTION 13 OR 15(d) OF THE SECURITIES EXCHANGE ACT OF 1934   For the fiscal year ended   ";
const ITEMS =
  "PART I   Item 1. Business   Item 1A. Risk Factors   Item 1B. Unresolved Staff Comments   Item 1C. Cybersecurity   Item 2. Properties   Item 3. Legal Proceedings   PART II   Item 5. Market for Registrant's Common Equity   Item 7. Management's Discussion and Analysis of Financial Condition and Results of Operations   Item 7A. Quantitative and Qualitative Disclosures About Market Risk   Item 8. Financial Statements and Supplementary Data   Item 9A. Controls and Procedures   ";

export function Backdrop() {
  return (
    <div className="backdrop" aria-hidden>
      <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="xMinYMin slice">
        <defs>
          <linearGradient id="wave-fill" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0" stopColor="var(--wave-1)" />
            <stop offset="1" stopColor="var(--wave-2)" />
          </linearGradient>
          <path id="microprint-upper" d={UPPER} />
          <path id="microprint-lower" d={LOWER} />
        </defs>
        <path d={FILL} fill="url(#wave-fill)" />
        <g fill="none" stroke="var(--wave-line)" strokeWidth="0.75">
          {STRANDS.map((d, i) => (
            <path key={i} d={d} opacity={i < 7 ? 1 : 0.6} />
          ))}
        </g>
        <g className="microprint">
          <text>
            <textPath href="#microprint-upper">{COVER.repeat(4)}</textPath>
          </text>
          <text>
            <textPath href="#microprint-lower">{ITEMS.repeat(3)}</textPath>
          </text>
        </g>
      </svg>
    </div>
  );
}
