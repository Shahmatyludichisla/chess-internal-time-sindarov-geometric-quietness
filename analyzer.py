#!/usr/bin/env python3
# ============================================
# Автор: Shahmatyludichisla
# Email: dipfritz19@gmail.com
# Проект: SLC Analyzer - Genetic Spine Version
# Дата: 2024-2025
# ============================================

import tkinter as tk
from tkinter import font
import chess
import chess.pgn
import chess.engine
import threading
import os
import sys
import re
from collections import Counter

# --- АВТО-ОПРЕДЕЛЕНИЕ ПУТЕЙ ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(BASE_DIR, "settings.txt")
PGN_FILE = os.path.join(BASE_DIR, "input.pgn")
LOG_FILE_FOR_MARKER = os.path.join(BASE_DIR, "spine.log")
ANOMALY_LOG = os.path.join(BASE_DIR, "detected_anomalies.txt")
LAST_MOVE_FILE = os.path.join(BASE_DIR, "last_move.txt") 

def load_config():
    path = os.path.join(BASE_DIR, "stockfish", "stockfish_main")
    if os.path.exists(path):
        return path
    return "/usr/games/stockfish"

ENGINE_PATH = load_config()

class ChessAnalyzer:
    def __init__(self, root):
        self.root = root
        self.root.title("SLC Analyzer - Genetic Spine Version")
        self.root.geometry("1200x850") 
        self.root.configure(bg="#1e1e1e")

        with open(ANOMALY_LOG, "w", encoding="utf-8") as f:
            f.write("--- Start Analysis Session ---\n")
        with open(LAST_MOVE_FILE, "w", encoding="utf-8") as f:
            f.write("")

        self.game_history = []
        self.current_move_idx = 0
        self.engine = None
        self.analysis_thread = None
        self.stop_analysis = False
        
        self.total_positions_analyzed = 0
        self.anomalous_positions_count = 0
        self.positions_with_anomalies = set() 
        self.current_line_data = [""] * 10 
        self.current_anomalous_indices = set() 
        self.current_second_moves_san = [""] * 10 
        self.current_full_chains = [""] * 10                 # без маркеров (для лога)
        self.current_full_chains_with_markers = [""] * 10    # с маркерами (для экспорта)
        
        self.genetic_vault = {} 

        self.header_font = font.Font(family="Monospace", size=12, weight="bold")
        self.line_font = font.Font(family="Monospace", size=10)

        # UI элементы
        self.top_frame = tk.Frame(root, bg="#2d2d2d", pady=5)
        self.top_frame.pack(fill="x")

        self.check_mode = tk.StringVar(value="Both") 
        self.btn_frame = tk.Frame(self.top_frame, bg="#2d2d2d")
        self.btn_frame.pack()
        
        for text, mode in [("Все", "Both"), ("Белые", "White"), ("Черные", "Black")]:
            tk.Radiobutton(self.btn_frame, text=text, variable=self.check_mode, value=mode,
                           bg="#2d2d2d", fg="#00ff00", selectcolor="#111", activebackground="#2d2d2d",
                           font=self.line_font, command=self.update_ui).pack(side="left", padx=10)

        self.time_limit_var = tk.DoubleVar(value=0.3)
        self.time_frame = tk.Frame(self.top_frame, bg="#2d2d2d")
        self.time_frame.pack(pady=2)
        tk.Label(self.time_frame, text="Time Limit (s):", fg="#abb2bf", bg="#2d2d2d", font=self.line_font).pack(side="left", padx=5)
        self.time_slider = tk.Scale(self.time_frame, from_=0.1, to=3.0, resolution=0.1, orient="horizontal", 
                                    variable=self.time_limit_var, bg="#2d2d2d", fg="#00ff00", 
                                    highlightthickness=0, length=200)
        self.time_slider.pack(side="left")

        self.threshold_var = tk.IntVar(value=6)
        self.thresh_frame = tk.Frame(self.top_frame, bg="#2d2d2d")
        self.thresh_frame.pack(pady=2)
        for text, val in [("30%", 3), ("40%", 4), ("60%", 6)]:
            tk.Radiobutton(self.thresh_frame, text=text, variable=self.threshold_var, value=val,
                           bg="#2d2d2d", fg="#e5c07b", selectcolor="#111", font=self.line_font).pack(side="left", padx=5)

        self.triad_label = tk.Label(self.top_frame, text="Загрузка...", fg="#00ff00", bg="#2d2d2d", font=self.header_font)
        self.triad_label.pack()

        self.info_label = tk.Label(self.top_frame, text="Depth: 0 | Time: 0s | Anomalies: 0.0%", fg="#abb2bf", bg="#2d2d2d", font=self.line_font)
        self.info_label.pack()

        self.lines_frame = tk.Frame(root, bg="#1e1e1e", pady=10)
        self.lines_frame.pack(fill="x")
        
        self.line_labels = []
        for i in range(10):
            lbl = tk.Label(self.lines_frame, text=f"{i+1}. ---", fg="#dcdfe4", bg="#1e1e1e", anchor="w", font=self.line_font, padx=20)
            lbl.pack(fill="x")
            self.line_labels.append(lbl)

        self.log_frame = tk.Frame(root, bg="#111", pady=5)
        self.log_frame.pack(fill="both", expand=True)
        tk.Label(self.log_frame, text=" [ GENETIC SPINE LOG ]", fg="#e5c07b", bg="#111", font=self.header_font).pack(anchor="w", padx=10)
        
        self.log_text = tk.Text(self.log_frame, bg="#000", fg="#00ff00", font=self.line_font, height=12)
        self.log_text.pack(fill="both", expand=True, padx=10, pady=5)
        self.log_text.config(state="disabled")

        self.stat_frame = tk.Frame(root, bg="#252525", pady=5)
        self.stat_frame.pack(fill="x", side="bottom")
        self.stat_label = tk.Label(self.stat_frame, text="---", fg="#00ff00", bg="#252525", font=self.line_font)
        self.stat_label.pack()

        self.root.bind("<Left>", lambda e: self.prev_move())
        self.root.bind("<Right>", lambda e: self.next_move())

        self.init_engine()
        self.load_pgn()
        self.update_ui()

    def init_engine(self):
        try:
            if not os.path.exists(ENGINE_PATH):
                self.triad_label.config(text=f"Движок не найден: {ENGINE_PATH}", fg="red")
                return
            self.engine = chess.engine.SimpleEngine.popen_uci(ENGINE_PATH)
        except Exception as e:
            self.triad_label.config(text=f"Ошибка движка: {e}", fg="red")

    def load_pgn(self):
        if os.path.exists(PGN_FILE):
            try:
                with open(PGN_FILE, encoding='utf-8') as f:
                    game = chess.pgn.read_game(f)
                    if game:
                        self.game_history = list(game.mainline_moves())
                        self.current_move_idx = 0
            except: pass

    def write_log(self, message):
        self.log_text.config(state="normal")
        self.log_text.insert(tk.END, f"{message}\n")
        self.log_text.see(tk.END)
        self.log_text.config(state="disabled")

    def update_ui(self):
        if not self.game_history: return
        self.current_line_data = [""] * 10
        self.current_second_moves_san = [""] * 10
        self.current_full_chains = [""] * 10
        self.current_full_chains_with_markers = [""] * 10
        
        temp_board = chess.Board()
        san_moves = []
        for m in self.game_history:
            san_moves.append(temp_board.san(m))
            temp_board.push(m)
        
        board = chess.Board()
        mode = self.check_mode.get()

        for i in range(self.current_move_idx):
            move = self.game_history[i]
            m_uci = move.uci()
            is_white_turn = (board.turn == chess.WHITE)
            
            if m_uci in self.genetic_vault:
                for entry in self.genetic_vault[m_uci]:
                    dist = (i + 1) - entry['origin_step']
                    if dist > 8: 
                        show = (mode == "Both") or (mode == "White" and is_white_turn) or (mode == "Black" and not is_white_turn)
                        if show:
                            self.write_log(f"[!] SPINE TRAP DETECTED: Move {i+1} ({san_moves[i]})")
                            self.write_log(f"    Gap: {dist} moves | Predicted at: {entry['origin_step']}")
                            clean_chain = [m.replace("(w)","").replace("(b)","").strip() for m in entry['chain']]
                            self.write_log(f"    Chain: {' -> '.join(clean_chain[:5])}...")
                            self.write_log("-" * 45)
                del self.genetic_vault[m_uci]
            board.push(move)

        idx = self.current_move_idx
        m1 = san_moves[idx-1] if idx > 0 else "..."
        m2 = san_moves[idx] if idx < len(san_moves) else "END"
        m3 = san_moves[idx+1] if idx + 1 < len(san_moves) else "..."
        turn_str = "Белые" if board.turn == chess.WHITE else "Черные"
        
        self.triad_label.config(text=f"Ход {turn_str}: {m1} -> {m2} -> {m3}", fg="#00ff00")
        for lbl in self.line_labels: lbl.config(text="---", bg="#1e1e1e", fg="#dcdfe4")
        self.start_analysis(board)

    def start_analysis(self, board):
        self.stop_analysis = True
        if self.analysis_thread and self.analysis_thread.is_alive(): 
            self.analysis_thread.join(0.1)
        self.stop_analysis = False
        self.analysis_thread = threading.Thread(target=self.run_engine, args=(board.fen(), self.current_move_idx), daemon=True)
        self.analysis_thread.start()

    def run_engine(self, fen, move_idx):
        board = chess.Board(fen)
        self.total_positions_analyzed += 1
        limit = self.time_limit_var.get()
        final_anomalies = ""
        
        current_mode = self.check_mode.get()
        is_white_turn = (board.turn == chess.WHITE)
        should_log = (current_mode == "Both") or (current_mode == "White" and is_white_turn) or (current_mode == "Black" and not is_white_turn)

        try:
            with self.engine.analysis(board, multipv=10) as analysis:
                for info in analysis:
                    if self.stop_analysis: break
                    if info.get("time", 0) >= limit:
                        self.stop_analysis = True
                        break

                    pv_idx = info.get("multipv")
                    if pv_idx and pv_idx <= 10:
                        pv_list = info.get("pv", [])
                        
                        # Собираем Genetic Spine (Цепочка предсказаний)
                        v_board = board.copy()
                        chain_san = []
                        for m in pv_list:
                            side = "(w)" if v_board.turn == chess.WHITE else "(b)"
                            san_m = v_board.san(m)
                            chain_san.append(f"{side}{san_m}")
                            
                            # Регистрация в хранилище для детекции ловушек в будущем
                            muci = m.uci()
                            if muci not in self.genetic_vault: self.genetic_vault[muci] = []
                            self.genetic_vault[muci].append({'origin_step': move_idx, 'chain': list(chain_san)})
                            v_board.push(m)

                        # Сохраняем цепочку с маркерами
                        self.current_full_chains_with_markers[pv_idx-1] = " ".join(chain_san)
                        # Сохраняем без маркеров (для Spine и совместимости)
                        self.current_full_chains[pv_idx-1] = " ".join([c.replace("(w)","").replace("(b)","") for c in chain_san])

                        # Логика детекции аномалий (повторов во вторых ходах)
                        if len(pv_list) >= 3:
                            t_board = board.copy()
                            t_board.push(pv_list[0]) 
                            t_board.push(pv_list[1]) 
                            self.current_second_moves_san[pv_idx-1] = t_board.san(pv_list[2])
                        
                        self.current_line_data[pv_idx-1] = "".join([m.uci() for m in pv_list])
                        
                        # Обновление UI
                        score = info.get("score").white()
                        score_val = score.score() / 100 if not score.is_mate() else f"M{score.mate()}"
                        
                        # Форматирование PV для вывода в лейбл
                        temp_board = board.copy()
                        fmt_pv = []
                        for i, m in enumerate(pv_list[:8]):
                            prefix = f"{temp_board.fullmove_number}." if temp_board.turn == chess.WHITE else ""
                            if i == 0 and temp_board.turn == chess.BLACK: prefix = f"{temp_board.fullmove_number}..."
                            fmt_pv.append(f"{prefix}{temp_board.san(m)}")
                            temp_board.push(m)

                        self.line_labels[pv_idx-1].config(
                            text=f"{pv_idx:2}. [{score_val: >6}] {' '.join(fmt_pv)}",
                            bg="#1e1e1e", fg="#dcdfe4"
                        )
                        
                        # Считаем аномалии (дубликаты)
                        counts = Counter([m for m in self.current_second_moves_san if m])
                        duplicates = []
                        thresh = self.threshold_var.get()
                        for m_san, count in counts.items():
                            if count > 1:
                                suffix = "!" if count >= thresh else ""
                                duplicates.append(f"{m_san}{suffix}-{count}")
                        
                        final_anomalies = " | ".join(duplicates)
                        self.stat_label.config(text=final_anomalies if final_anomalies else "---")

            # --- ЭКСПОРТ ДАННЫХ ДЛЯ ДЕТЕКТОРА (last_move.txt) ---
            if should_log:
                with open(LAST_MOVE_FILE, "w", encoding="utf-8") as lf:
                    # Строка 1: Приоритетные ходы
                    lf.write((final_anomalies if final_anomalies else "---") + "\n")
                    # Строки 2-11: Все 10 линий с маркерами
                    for i in range(1, 11):
                        chain = self.current_full_chains_with_markers[i-1] if self.current_full_chains_with_markers[i-1] else ""
                        lf.write(f"PV{i}: {chain}\n")

        except Exception: pass

    def next_move(self):
        if self.current_move_idx < len(self.game_history):
            self.current_move_idx += 1
            self.update_ui()

    def prev_move(self):
        if self.current_move_idx > 0:
            self.current_move_idx -= 1
            self.update_ui()

if __name__ == "__main__":
    root = tk.Tk()
    app = ChessAnalyzer(root)
    root.mainloop()
