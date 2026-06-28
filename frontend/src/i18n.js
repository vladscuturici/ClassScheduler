// i18n.js  — all UI strings in English and Romanian

export const translations = {
  en: {
    // ── Start page ──────────────────────────────────────────────────────────
    welcome:            'Class Scheduler',
    welcome_sub:        'Generate conflict-free school timetables in minutes.',
    btn_download:       'Download template',
    btn_download_sub:   'Get the blank Excel file to fill in',
    btn_import:         'Import Excel file',
    btn_import_sub:     'Upload your completed schedule file',
    btn_continue:       'Continue',
    upload_hint:        'Drag & drop your .xlsx file here, or click to browse',
    upload_success:     'File uploaded successfully',
    upload_error:       'Could not read the file. Please use the template.',
    uploading:          'Uploading…',
    no_file_yet:        'No file uploaded yet — import one to continue.',
    file_ready:         'Ready:',
    drop_active:        'Drop it!',

    // ── Step bar ────────────────────────────────────────────────────────────
    step_start:         'Import',
    step_customize:     'Customize',
    step_classes:       'Classes',
    step_teachers:      'Teachers',
    step_review:        'Review',
    step_searching:     'Generate',
    step_result:        'Schedule',

    // ── Language names ──────────────────────────────────────────────────────
    lang_en: 'English',
    lang_ro: 'Română',
  },

  ro: {
    // ── Start page ──────────────────────────────────────────────────────────
    welcome:            'Planificator de Ore',
    welcome_sub:        'Generează orare școlare fără conflicte în câteva minute.',
    btn_download:       'Descarcă șablonul',
    btn_download_sub:   'Obține fișierul Excel necompletat',
    btn_import:         'Importă fișier Excel',
    btn_import_sub:     'Încarcă fișierul tău completat',
    btn_continue:       'Continuă',
    upload_hint:        'Trage fișierul .xlsx aici sau apasă pentru a selecta',
    upload_success:     'Fișier încărcat cu succes',
    upload_error:       'Nu s-a putut citi fișierul. Folosește șablonul.',
    uploading:          'Se încarcă…',
    no_file_yet:        'Niciun fișier încărcat — importă unul pentru a continua.',
    file_ready:         'Pregătit:',
    drop_active:        'Dă-i drumul!',

    // ── Step bar ────────────────────────────────────────────────────────────
    step_start:         'Import',
    step_customize:     'Personalizare',
    step_classes:       'Clase',
    step_teachers:      'Profesori',
    step_review:        'Revizuire',
    step_searching:     'Generare',
    step_result:        'Orar',

    // ── Language names ──────────────────────────────────────────────────────
    lang_en: 'English',
    lang_ro: 'Română',
  },
}

// Simple hook — returns a t() function for the current language
import { useStore } from './store'

export function useT() {
  const lang = useStore(s => s.lang)
  return (key) => translations[lang]?.[key] ?? translations.en[key] ?? key
}
