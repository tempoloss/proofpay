import { useCallback, useState } from "react";

/**
 * The funder key is the only credential of a bounty: whoever holds it can
 * fund, release, reject and cancel. The server keeps a hash; the key itself
 * lives in this browser only.
 */
const storageKey = (bountyId: string): string => `proofpay:key:${bountyId}`;

export const saveFunderKey = (bountyId: string, key: string): void => {
  localStorage.setItem(storageKey(bountyId), key);
};

export const loadFunderKey = (bountyId: string): string | null => localStorage.getItem(storageKey(bountyId));

export const forgetFunderKey = (bountyId: string): void => {
  localStorage.removeItem(storageKey(bountyId));
};

/** The key for a bounty and a way to forget it on this device. */
export function useFunderKey(bountyId: string): { key: string | null; forget: () => void } {
  const [key, setKey] = useState(() => loadFunderKey(bountyId));
  const forget = useCallback(() => {
    forgetFunderKey(bountyId);
    setKey(null);
  }, [bountyId]);
  return { key, forget };
}
