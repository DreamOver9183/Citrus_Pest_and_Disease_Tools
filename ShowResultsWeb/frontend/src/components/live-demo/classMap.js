// 類別代碼 → 顯示名稱 / 語意分類 / 徽章樣式。
//
// 查表以 YOLO checkpoint 內嵌的 model.names 為鍵（inference.py 直接回傳原始類別字串）。
// 查不到時 ResultCard 會退回灰色的 unknown 徽章，因此這張表落後於模型版本的話，
// 畫面上會變成一片沒有語意的英文原名。
//
// color 必須是完整靜態 Tailwind 字串（JIT 掃不到樣板字串組出的 class）。
// type 只有 'pest' 會顯示紅點，其餘為琥珀點（見 ResultCard）。
export const CLASS_MAP = {
  // === 現行 8 類別模型（YOLO26n_P2_Citrus v5 / v8）===
  // 這是目前所有 checkpoint 實際輸出的類別名，必須與 model.names 完全一致（含大小寫）。
  'Oily_Spot': { name: '油斑病 (Oily Spot)', type: 'damage', color: 'bg-amber-500/10 text-amber-400 border-amber-500/20' },
  'Canker': { name: '潰瘍病 (Canker)', type: 'damage', color: 'bg-red-500/10 text-red-400 border-red-500/20' },
  'Sooty_Mold': { name: '煤煙病 (Sooty Mold)', type: 'damage', color: 'bg-slate-500/10 text-slate-300 border-slate-500/20' },
  'Black_Spot': { name: '黑點病 (Black Spot)', type: 'damage', color: 'bg-yellow-500/10 text-yellow-400 border-yellow-500/20' },
  'Scale_Insect': { name: '介殼蟲 (Scale Insect)', type: 'pest', color: 'bg-rose-500/10 text-rose-400 border-rose-500/20' },
  'Citrus_Leaf_Miner': { name: '潛葉蛾 (Leaf Miner)', type: 'pest', color: 'bg-lime-500/10 text-lime-400 border-lime-500/20' },
  'Thrips': { name: '薊馬 (Thrips)', type: 'pest', color: 'bg-violet-500/10 text-violet-400 border-violet-500/20' },
  'Aphid': { name: '蚜蟲 (Aphid)', type: 'pest', color: 'bg-orange-500/10 text-orange-400 border-orange-500/20' },

  // === 舊版 12 類別模型（保留以相容既有權重檔）===
  'aphid': { name: '蚜蟲 (Aphid)', type: 'pest', color: 'bg-red-500/10 text-red-400 border-red-500/20' },
  'aphid_leaf_damage': { name: '蚜蟲葉片傷害 (Aphid Damage)', type: 'damage', color: 'bg-amber-500/10 text-amber-400 border-amber-500/20' },
  'leaf': { name: '健康葉片 (Healthy Leaf)', type: 'normal', color: 'bg-emerald-500/10 text-emerald-400 border-emerald-500/20' },
  'Leaf_Miner_Leaf_Damage': { name: '潛葉蛾傷害 (Miner Damage)', type: 'damage', color: 'bg-yellow-500/10 text-yellow-400 border-yellow-500/20' },
  'Black Scale Insect': { name: '黑褐圓蚧 (Black Scale)', type: 'pest', color: 'bg-rose-500/10 text-rose-400 border-rose-500/20' },
  'Brown Scale Insect': { name: '褐軟蚧 (Brown Scale)', type: 'pest', color: 'bg-pink-500/10 text-pink-400 border-pink-500/20' },
  'Green Coffee Scale Insect': { name: '綠咖啡蚧 (Green Scale)', type: 'pest', color: 'bg-purple-500/10 text-purple-400 border-purple-500/20' },
  'White Scale Insect': { name: '白盾蚧 (White Scale)', type: 'pest', color: 'bg-indigo-500/10 text-indigo-400 border-indigo-500/20' },
  'Thysanoptera': { name: '薊馬 (Thrips)', type: 'pest', color: 'bg-violet-500/10 text-violet-400 border-violet-500/20' },
  'thirps_leaf_damage': { name: '薊馬葉片傷害 (Thrips Damage)', type: 'damage', color: 'bg-orange-500/10 text-orange-400 border-orange-500/20' },

  // SSD 專屬短縮寫對應
  'H_MC': { name: '健康果實 (H_MC)', type: 'normal', color: 'bg-emerald-500/10 text-emerald-400 border-emerald-500/20' },
  'H_PK': { name: '健康果實 (H_PK)', type: 'normal', color: 'bg-emerald-500/10 text-emerald-400 border-emerald-500/20' },
  'D_GS': { name: '綠咖啡蚧 (D_GS)', type: 'pest', color: 'bg-purple-500/10 text-purple-400 border-purple-500/20' },
  'D_MN': { name: '潛葉蛾傷害 (D_MN)', type: 'damage', color: 'bg-yellow-500/10 text-yellow-400 border-yellow-500/20' },
  'D_SM': { name: '煤煙病 (D_SM)', type: 'damage', color: 'bg-slate-500/10 text-slate-400 border-slate-500/20' },
  'D_CK': { name: '潰瘍病 (D_CK)', type: 'damage', color: 'bg-red-500/10 text-red-400 border-red-500/20' },
  'P_AP': { name: '蚜蟲 (P_AP)', type: 'pest', color: 'bg-red-500/10 text-red-400 border-red-500/20' },
  'P_AP_LD': { name: '蚜蟲傷害 (P_AP_LD)', type: 'damage', color: 'bg-amber-500/10 text-amber-400 border-amber-500/20' },
  'P_SI': { name: '介殼蟲 (P_SI)', type: 'pest', color: 'bg-rose-500/10 text-rose-400 border-rose-500/20' },
  'P_TP': { name: '薊馬 (P_TP)', type: 'pest', color: 'bg-violet-500/10 text-violet-400 border-violet-500/20' },
  'P_TP_LD': { name: '薊馬傷害 (P_TP_LD)', type: 'damage', color: 'bg-orange-500/10 text-orange-400 border-orange-500/20' },
  'P_LM_LD': { name: '潛葉蛾傷害 (P_LM_LD)', type: 'damage', color: 'bg-yellow-500/10 text-yellow-400 border-yellow-500/20' }
};
