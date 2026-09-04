interface NaviviPinProps {
    label?: string;
    pinType: "start" | "end" | "stopby" | "normal" | "drawn";
    className?: string;
}

export function NaviPin({ label, pinType, className = "" }: NaviviPinProps) {
    let fill = "#4287f5";
    if (pinType === "start") fill = "#038813";
    if (pinType === "end") fill = "#d90f51";
    if (pinType === "drawn") fill = "#ff790c";
    if (pinType === "stopby") fill = "#33261c";

    return (
        <svg
            xmlns="http://www.w3.org/2000/svg"
            viewBox="0 0 191 275"
            width="32" height="46"
            className={`drop-shadow-xl ${className}`}
        >
            <circle cx="95.5" cy="90" r="62" fill="#fff" />
            
            <path
                fillRule="evenodd"
                fill={fill}
                d="m0 91c0-49.77 42.69-90 95.5-90 52.81 0 95.5 40.23 95.5 90 0 8-1.1 15.75-3.17 23.12-6.24 35.97-53.59 160.73-92.33 160.73-33.57 0-88.97-127.86-92.96-163.12-1.66-6.65-2.54-13.59-2.54-20.73zm159.06-1c0-34.87-28.19-63.06-63.06-63.06-34.87 0-63.06 28.19-63.06 63.06 0 34.87 28.19 63.06 63.06 63.06 34.87 0 63.06-28.19 63.06-63.06z"
            />

            <text
                x="95.5" y={label && label.length > 2 ? "105" : "110"} 
                textAnchor="middle"
                fontSize={label && label.length > 2 ? "45" : "65"}
                fontWeight="900" fontFamily="Inter, system-ui, sans-serif"
                fill="#111"
            >
                {label}
            </text>
        </svg>
    )
}