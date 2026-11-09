// Where a visual is shown decides what its copies and downloads can carry: in Wizard, the rows of the sources it cites
// (the data behind it) and a save into the person's Downloads folder; on the Pages site, only what the case publishes
// (its values, its sources' names and queries, never their rows) and the browser's own download.
import {createContext} from 'react';
import type {Column, DataMode} from './types';

export interface VisualSource {
  id: string;
  name: string;
  dataMode?: string | null;
  asOf?: string | null;
  totalRows?: number | null;
  truncated?: boolean | null;
  /** The SQL, the portal steps or the request that read it, as text. */
  query?: string | null;
}

/** The rows one cited source returned, as Wizard keeps them. */
export interface SourceRows { id: string; columns: Column[]; rows: (string | number | null)[][]; truncated?: boolean }

export interface SavedExport { id: string; filename: string; folder: string }

export interface VisualEnv {
  /** The answer's data label, carried onto every copy and download. */
  dataMode: DataMode | null;
  /** The sources a visual cites; `rows` only where the rows may be shown (in Wizard, never on the site). */
  sources: (ids: string[]) => Promise<{sources: VisualSource[]; rows: SourceRows[]}>;
  /** True where the Excel file can carry the cited sources' rows. */
  rowsBehind: boolean;
  /** Wizard on the person's own PC: save into Downloads and say where. Null: the browser downloads it instead. */
  save?: (file: Blob, filename: string) => Promise<SavedExport | null>;
  open?: (saved: SavedExport) => Promise<void>;
}

export const NO_SOURCES: VisualEnv = {dataMode: null, rowsBehind: false, sources: async () => ({sources: [], rows: []})};

export const VisualEnvContext = createContext<VisualEnv>(NO_SOURCES);
