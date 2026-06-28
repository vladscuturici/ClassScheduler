// store.js — global state shared across all pages
import { create } from 'zustand'

export const useStore = create((set) => ({
  // ── Language ─────────────────────────────────────────────────────────────
  lang: localStorage.getItem('lang') || 'en',
  setLang: (lang) => {
    localStorage.setItem('lang', lang)
    set({ lang })
  },

  // ── Session (set after /api/upload) ──────────────────────────────────────
  sessionId:   null,
  parsedData:  null,   // raw ParsedData from the API
  uploadedFileName: null,

  setSession: (sessionId, parsedData, fileName) =>
    set({ sessionId, parsedData, uploadedFileName: fileName }),

  // ── User-edited data (carried through wizard) ─────────────────────────────
  editedClasses:   null,   // list[ClassInfo] after customise / constraint pages
  editedTeachers:  null,   // list[TeacherInfo]
  solveParams:     { max_solutions: 1, use_balanced_difficulty: false },

  setEditedClasses:  (classes)  => set({ editedClasses: classes }),
  setEditedTeachers: (teachers) => set({ editedTeachers: teachers }),
  setSolveParams:    (params)   => set({ solveParams: params }),

  // ── Solved schedule ───────────────────────────────────────────────────────
  scheduleGrid: null,
  setScheduleGrid: (grid) => set({ scheduleGrid: grid }),

  // ── Wizard step ───────────────────────────────────────────────────────────
  step: 0,
  setStep: (step) => set({ step }),
}))
