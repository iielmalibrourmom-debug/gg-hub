import React from "react";
export default function DeviceArt({
  keyboard = false,
  accent = "#1196ff",
  className = "",
}) {
  if (keyboard)
    return (
      <svg
        className={"device-art " + className}
        viewBox="0 0 480 240"
        role="img"
        aria-label="Keyboard illustration"
      >
        <defs>
          <linearGradient id="kb" x2="0" y2="1">
            <stop stopColor="#484a4e" />
            <stop offset="1" stopColor="#161719" />
          </linearGradient>
        </defs>
        <rect
          x="10"
          y="28"
          width="460"
          height="178"
          rx="14"
          fill="url(#kb)"
          stroke="#65666a"
        />
        <path d="M26 214h428" stroke="#0b0b0b" strokeWidth="9" />
        {Array.from({ length: 5 }, (_, r) =>
          Array.from({ length: 14 }, (_, c) => (
            <g key={r + "-" + c}>
              <rect
                x={24 + c * 30}
                y={43 + r * 29}
                width={c === 13 ? 40 : 25}
                height="24"
                rx="3"
                fill="#161719"
                stroke="#45464a"
              />
              <path
                d={`M${31 + c * 30} ${51 + r * 29}h9`}
                stroke={accent}
                strokeWidth="2"
                opacity={0.3 + ((r + c) % 4) * 0.2}
              />
            </g>
          )),
        )}
        <rect
          x="144"
          y="160"
          width="157"
          height="24"
          rx="3"
          fill="#18191b"
          stroke="#45464a"
        />
      </svg>
    );
  return (
    <svg
      className={"device-art " + className}
      viewBox="0 0 240 330"
      role="img"
      aria-label="Mouse illustration"
    >
      <defs>
        <linearGradient id="shell" x1="0" x2="1">
          <stop stopColor="#929596" />
          <stop offset=".22" stopColor="#e6e7e7" />
          <stop offset=".52" stopColor="#f7f7f5" />
          <stop offset=".85" stopColor="#b8bbbc" />
          <stop offset="1" stopColor="#676a6b" />
        </linearGradient>
        <linearGradient id="buttons" x1="0" x2="1">
          <stop stopColor="#17191a" />
          <stop offset=".42" stopColor="#393b3b" />
          <stop offset=".55" stopColor="#202223" />
          <stop offset="1" stopColor="#111314" />
        </linearGradient>
        <filter id="shadow">
          <feDropShadow dy="8" stdDeviation="8" floodOpacity=".5" />
        </filter>
      </defs>
      <g filter="url(#shadow)">
        <path
          d="M48 101C48 31 72 12 121 12s72 29 72 89l8 136c3 49-30 78-80 78S37 288 40 237z"
          fill="url(#shell)"
          stroke="#757879"
        />
        <path d="M50 99c0-58 27-86 70-87l-2 137-67-8z" fill="url(#buttons)" />
        <path d="M122 12c49 1 70 30 70 88l-1 40-70 9z" fill="url(#buttons)" />
        <path d="M120 16v40m0 47v41" stroke="#080909" strokeWidth="2" />
        <rect
          x="109"
          y="53"
          width="22"
          height="50"
          rx="10"
          fill="#030404"
          stroke="#535657"
        />
        <rect x="114" y="59" width="12" height="38" rx="5" fill="#4a4d4d" />
        {[65, 71, 77, 83, 89].map((y) => (
          <path key={y} d={`M115 ${y}h10`} stroke="#242727" />
        ))}
        <rect x="37" y="119" width="6" height="37" rx="3" fill="#262829" />
        <rect x="35" y="161" width="6" height="32" rx="3" fill="#262829" />
        <text
          x="120"
          y="242"
          fill="#383c3d"
          fontFamily="Arial,sans-serif"
          fontWeight="900"
          fontSize="30"
          textAnchor="middle"
        >
          GG
        </text>
        <path
          d="M60 270c15 26 86 38 122-4"
          fill="none"
          stroke="#ffffff"
          strokeOpacity=".2"
        />
      </g>
    </svg>
  );
}
