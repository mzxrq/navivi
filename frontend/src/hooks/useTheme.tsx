import { createContext, useContext, useEffect, useState, } from 'react';

type Theme = 'dark' | 'light' | 'system';
type MapTheme = 'dark' | 'light' | 'sync';

type ThemeProviderProps = {
    children: React.ReactNode;
    defaultTheme?: Theme;
}

type ThemeProviderState = {
    theme: Theme;
    setTheme: (theme: Theme) => void;
    mapTheme: MapTheme;
    setMapTheme: (theme: MapTheme) => void;
}

const ThemeProviderContext = createContext<ThemeProviderState | undefined>(undefined);

export function ThemeProvider({ children, defaultTheme = 'system' }: ThemeProviderProps) {
    const [theme, setTheme] = useState<Theme>(
        () => (localStorage.getItem('app-theme') as Theme || defaultTheme)
    );

    const [mapTheme, setMapTheme] = useState<MapTheme>(
        () => (localStorage.getItem('map-theme') as MapTheme || 'sync')
    );

    useEffect(() => {
        const root = window.document.documentElement;
        root.classList.remove('light', 'dark');

        if (theme === 'system') {
            const systemTheme = window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
            root.classList.add(systemTheme);
            return;
        }

        root.classList.add(theme);
    }, [theme]);

    const value = {
        theme,
        setTheme: (theme: Theme) => {
            localStorage.setItem('app-theme', theme);
            setTheme(theme);
        },
        mapTheme,
        setMapTheme: (theme: MapTheme) => {
            localStorage.setItem('map-theme', theme);
            setMapTheme(theme);
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