import { type ClassValue, clsx } from "clsx";
import { twMerge } from "tailwind-merge";

/** Joins class names; later Tailwind utilities win over earlier ones. */
export const cn = (...inputs: ClassValue[]): string => twMerge(clsx(inputs));
