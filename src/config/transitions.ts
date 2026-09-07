export const stockTransitions = [
    { value: "none", label: "Hard Cut", duration: 0 },
    { value: "crossfade", label: "Crossfade", duration: 1.0 },
    { value: "dip-to-black", label: "Dip to Black", duration: 0.5 },
    { value: "dip-to-white", label: "Dip to White", duration: 0.5 },
] as const;

export type TransitionType = typeof stockTransitions[number]["value"];