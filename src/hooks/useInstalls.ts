import { useSyncExternalStore } from "react";
import { getInstalls, subscribeInstalls } from "../services/installs";

export const useInstalls = () => useSyncExternalStore(subscribeInstalls, getInstalls);
