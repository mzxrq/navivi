import { createContext, useContext, useEffect, useState, } from 'react';

type Theme = 'dark' | 'light' | 'system';
type AccentTheme = 'navi' | 'emerald' | 'violet' | 'amber' | 'rose';

type ThemeProviderProps = {
    children: React.ReactNode;
    defaultTheme?: Theme;
}

type ThemeProviderState = {
    theme: Theme;
    setTheme: (theme: Theme) => void;
    accentTheme: AccentTheme;
    setAccentTheme: (theme: AccentTheme) => void;
}

const ThemeProviderContext = createContext<ThemeProviderState | undefined>(undefined);

export function ThemeProvider({ children, defaultTheme = 'system' }: ThemeProviderProps) {
    const [theme, setTheme] = useState<Theme>(
        () => (localStorage.getItem('app-theme') as Theme || defaultTheme)
    );

    const [accentTheme, setAccentTheme] = useState<AccentTheme>(
        () => (localStorage.getItem('accent-theme') as AccentTheme || 'navi')
    );

    useEffect(() => {
        const root = window.document.documentElement;
        root.classList.remove('light', 'dark');

        if (theme === 'system') {
            const systemTheme = window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
            root.classList.add(systemTheme);
            return;
        } else {
            root.classList.add(theme);
        }

        root.classList.add(theme);
    }, [theme]);

    useEffect(() => {
        const root = window.document.documentElement;
        if (accentTheme === 'navi') {
            root.removeAttribute('data-theme');
        } else {
            root.setAttribute('data-theme', accentTheme);
        }
    }, [accentTheme]);

    const value = {
        theme,
        setTheme: (theme: Theme) => {
            localStorage.setItem('app-theme', theme);
            setTheme(theme);
        },
        accentTheme,
        setAccentTheme: (theme: AccentTheme) => {
            localStorage.setItem('accent-theme', theme);
            setAccentTheme(theme);
        },
    };

    return (
        <ThemeProviderContext.Provider value={value}>{children}</ThemeProviderContext.Provider>
    );
}

export const useTheme = () => {
    const context = useContext(ThemeProviderContext);
    if (context === undefined) throw new Error('useTheme must be used within a ThemeProvider');
    return context;
};