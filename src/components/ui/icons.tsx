import React from "react";
export {
  AlertTriangle,
  RefreshCw, //ErrorBoundary
  X,
  BookOpen,
  Key,
  ExternalLink,
  Moon,
  Sun,
  Monitor,
  Map, //AppSettings
  Folder,
  Loader2, //Map, //SaveAs
  Palette, //X, //MapSettings
  Search,
  MapPin, //X, Loader2, //LocationSearch
  CheckCircle,
  XCircle,
  Info,
  PlayCircle, //Loader2, AlertTriangle, //RenderOverlay
  Mic,
  Sparkles,
  Settings2,
  Loader, //ScriptInput
  //Info, //ScrubInput
  Menu,
  Minus,
  Square,
  ChevronRight,
  PanelBottom,
  Undo2,
  Redo2, //X, Map, Settings2 //TitleBar
  Car,
  Footprints,
  Ruler,
  Plane,
  Trash2,
  Edit,
  CopyPlus,
  CornerDownLeft,
  Ship, //WaypointLayer
  UploadCloud, //MapPin //MapArea
  FileVideo,
  Map as MapIcon,
  Route,
  Play,
  PencilSparkles,
  MapPinIcon,
  Clapperboard,
  Hourglass,
  ToolCase,
  ChevronDown, // ChevronRight, Trash2, Car, Footprints, Ruler, Plane, Square, Mic, Sparkles, Settings2, Ship, Loader, //Sidebar
  Film,
  SkipBack,
  SkipForward,
  Volume2,
  Maximize,
  PictureInPicture, // Play,  Settings2, //VideoArea
  ChevronLeft,
  Image as ImageIcon, // X, Trash2, MapPin, Settings2,Mic, //WaypointEditor
  GripVertical,
  Edit2, //X, Image as ImageIcon, Mic //WaypointItem
  FolderPlus,
  Clock, // MapPin, Monitor, ChevronRight, //NewProject
  Plus,
  FolderOpen,
  LayoutGrid,
  List, //Map, Clock //TitleScreen
  Cpu,
  Check, // EngineSelect
  Pause,
  Scissors,
  Magnet,
  MousePointer2,
  Type,
  Video,
  Download,
  Subtitles, // TimelineView
  File,
  FileAudio,
  FolderSync, // MediaPool
  ZoomIn,
  ZoomOut, // TimelineView
  Layers, //TimelineTrack
  MonitorPlay, //ExportPanel
  CheckCircle2,
  AlertCircle, // Toast
  Copy,
  CircleDashed,
  History,
  Bell, // StatusBar
  Settings,
  Save, // AppSettings
  Pencil,
  SplinePointer,
  Undo,
  Eraser,
  MapPinPen, // MapArea
  MapPinPlus,
  MapPinned,
  Waypoints as WP,
  Eye,
  EyeOff,
  VolumeX,
  Lock,
  Unlock,
  LinkIcon,
  UnlinkIcon,
  Edit3,
  FileText,
  ArrowRight,
  MoreVertical, //TimelineView
  Navigation,
  Globe,
  ChevronUp,
  ChevronLeftCircle,
  Box,
  SwitchCamera,
  Lightbulb,
  Music,
} from "lucide-react";
export {
  ArrowLeft,
  ArrowUp,
  ArrowDown,
  MoveUpRight,
  MoveUpLeft,
  MoveDownRight,
  MoveDownLeft,
  LocateFixed, // WaypointEditor
  ClipboardPaste,
  Flag, // ContextMenu
  SquareTerminal, // PipelineLogPanel
  Maximize2, // RenderOverlay
  Minimize2,
  RotateCcw,
  Zap,
  Bold, // text style editors
  Italic,
  Underline,
  AlignLeft,
  AlignCenter,
  AlignRight,
  AlignVerticalJustifyStart,
  AlignVerticalJustifyCenter,
  AlignVerticalJustifyEnd,
} from "lucide-react";

export const Navivi = ({
  className = "",
  ...props
}: React.SVGProps<SVGSVGElement>) => (
  <svg
    xmlns="http://www.w3.org/2000/svg"
    viewBox="26 12 160 160"
    className={className}
    {...props}
  >
    <defs>
      <linearGradient
        id="navivi-grad"
        x1="30"
        y1="125"
        x2="160"
        y2="40"
        gradientUnits="userSpaceOnUse"
      >
        <stop offset="0%" stopColor="#3b82f6" />
        <stop offset="45%" stopColor="#8b5cf6" />
        <stop offset="100%" stopColor="#ff7e5f" />
      </linearGradient>
    </defs>
    <path
      d="m60 150 12-85q3-25 16 0l34 62.5q13 22.5 15.5 9.25L144 97"
      fill="none"
      stroke="url(#navivi-grad)"
      strokeWidth="22"
      strokeLinecap="round"
      strokeLinejoin="round"
    />
    <circle cx="60" cy="150" r="18" fill="url(#navivi-grad)" />
    <circle cx="60" cy="150" r="9" fill="#fff" />
    <path
      fill="url(#navivi-grad)"
      stroke="url(#navivi-grad)"
      strokeWidth="19"
      strokeLinejoin="round"
      transform="matrix(.42 0 0 .42 140 25)"
      d="M21.65 118.46c-10.06-2.7-20.47-45.45-21-53.76-.54-8.58-.03-21.19 2.59-30.99 5-18.64 26.18-29.12 47.4-23.43 21.21 5.68 34.32 25.35 29.33 43.99-2.44 9.1-9.3 20.05-14.44 27.82-7.16 10.83-33.02 39.28-43.88 36.37z"
    />
    <path
      fill="#fff"
      stroke="#fff"
      strokeWidth="8"
      strokeLinejoin="round"
      d="m153 41 9 8-10 5z"
    />
  </svg>
);

export const NaviviType = ({
  className = "",
  ...props
}: React.SVGProps<SVGSVGElement>) => (
  <svg
    xmlns="http://www.w3.org/2000/svg"
    viewBox="150 0 761 185"
    className={className}
    {...props}
  >
    <g fillRule="evenodd">
      <path
        d="M170.66 164.28s-.61-66.11-.61-126.77c0-11.69-.31-19.71.59-18.15 5.7 9.94-1.27.29 50.86 67.34 50.75 68.83 22.68 30.51 50.78 69.1 6.46 7.08 11.31 13.68 11.86 3.76-.53-142.71-.53-140.18-.53-140.18"
        fill="none"
        stroke="currentColor"
        strokeLinecap="round"
        strokeLinejoin="round"
        strokeWidth="39"
      />
      <path
        d="M385.53 164.02c-27.04 0-48.89-21.85-48.89-48.9 0-27.04 21.85-48.89 48.89-48.89s48.9 21.85 48.9 48.89c0 27.05-21.86 48.9-48.9 48.9m59.92.15c0-98.79-54.04-97.87-58.88-97.87"
        fill="none"
        stroke="currentColor"
        strokeLinecap="round"
        strokeLinejoin="round"
        strokeWidth="39"
      />
      <path
        d="M482.93 66.04c35 26.11 54.14 96.96 55.14 97.96.94.94 12.93-60.12 55.14-97.96"
        fill="none"
        stroke="currentColor"
        strokeLinecap="round"
        strokeLinejoin="round"
        strokeWidth="39"
      />
      <path
        d="M716.93 66.04c35 26.11 54.14 96.96 55.14 97.96.94.94 12.93-60.12 55.14-97.96"
        fill="none"
        stroke="currentColor"
        strokeLinecap="round"
        strokeLinejoin="round"
        strokeWidth="39"
      />
      <path
        d="M666.52 50.61c-10.1 7.57-24.39 5.52-31.96-4.58-7.57-10.11-5.52-24.4 4.58-31.97 10.11-7.57 24.4-5.52 31.97 4.59 7.57 10.1 5.52 24.39-4.59 31.96"
        fill="currentColor"
      />
      <path
        d="M658.98 81.78c-.8 1.73-1.96 181.35-10.81-.12z"
        fill="none"
        stroke="currentColor"
        strokeLinecap="round"
        strokeLinejoin="round"
        strokeWidth="39"
      />
      <path
        d="M885.98 81.78c-.8 1.73-1.96 181.35-10.81-.12z"
        fill="none"
        stroke="currentColor"
        strokeLinecap="round"
        strokeLinejoin="round"
        strokeWidth="39"
      />
      <path
        d="M879.83 55.17c-12.62 0-22.83-10.21-22.83-22.83 0-12.63 10.21-22.83 22.83-22.83 12.63 0 22.84 10.2 22.84 22.83 0 12.62-10.21 22.83-22.84 22.83"
        fill="currentColor"
      />
    </g>
  </svg>
);
