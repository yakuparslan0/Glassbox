// Thin aliases over the GENERATED event types (no hand-written event shapes live here).
import type { ObjEntry, MapEntry, OtherValue, Prim, Ref, SeqEntry, RunEvent } from "./generated";

export type { RunEvent } from "./generated";
export type Val = Prim | Ref | OtherValue;
export type HeapEntry = SeqEntry | MapEntry | ObjEntry | OtherValue;
export type HeapMap = Record<string, HeapEntry>;

export interface FrameState {
  frame: number;
  func: string;
  line: number;
  locals: Record<string, Val>;
}

export interface ViewState {
  stack: FrameState[];
  globals: Record<string, Val>;
  heap: HeapMap;
}

export type StepEvent = Extract<RunEvent, { step: number }>;
export const isRef = (v: Val): v is Ref => "ref" in v;
