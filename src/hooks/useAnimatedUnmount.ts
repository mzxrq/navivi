import { useState, useEffect } from "react";

export function useAnimatedUnmount(isOpen: boolean, delay: number = 200) {
    const [shouldRender, setShouldRender] = useState(isOpen);
    const [isAnimatingOut, setIsAnimatingOut] = useState(false);

    useEffect(() => {
        let timeoutId: ReturnType<typeof setTimeout>;
        if (isOpen) {
            // told to open -> remder -> clear exit
            setShouldRender(true); setIsAnimatingOut(false);
        } else if (shouldRender) {
            setIsAnimatingOut(true);

            timeoutId = setTimeout(() => {
                setShouldRender(false);
            }, delay);
        }
        return () => clearTimeout(timeoutId);
    }), [isOpen, shouldRender, delay];

    return { shouldRender, isAnimatingOut };
}