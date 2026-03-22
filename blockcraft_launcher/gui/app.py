import json
import os
import shlex
import shutil
import subprocess
import sys
import threading
import urllib.parse
from datetime import datetime
from pathlib import Path
from tkinter import (
    Tk,
    Frame,
    Label,
    Button,
    Listbox,
    Scrollbar,
    Entry,
    StringVar,
    Toplevel,
    filedialog,
    messagebox,
    SINGLE,
    END,
    OptionMenu,
    Text,
    DISABLED,
    NORMAL,
)

from ..config import load_config, save_config
from ..constants import APP_NAME, LAUNCHER_VERSION
from ..fs_utils import clean_dir, copy_tree, migrate_legacy_global_resources
from ..importers import import_curseforge_modpack, import_modrinth_modpack
from ..instance import (
    create_default_instance_json,
    get_instance_loader,
    get_instance_minecraft_version,
    infer_minecraft_version_from_args_filename,
    load_instance_json,
    normalize_loader_name,
    save_instance_json,
)
from ..java_runtime import ensure_java_runtime, get_java_executable
from ..mod_api import curseforge as cf
from ..mod_api import modrinth as mr
from ..mojang import download_vanilla_version
from ..modpacks import ensure_modpacks_dir, list_modpacks
from ..paths import INSTALL_DIR, MODPACKS_DIR, VANILLA_DIR


class MinecraftLauncherApp:
    def __init__(self, root: Tk):
        self.root = root
        self.root.title(APP_NAME)
        self.root.geometry("980x540")
        self.root.minsize(880, 460)

        self.bg_color = "#2b3a1f"
        self.panel_color = "#3e4f29"
        self.button_color = "#5f7a35"
        self.button_hover_color = "#7ea843"
        self.accent_color = "#c2a162"
        self.text_color = "#f4f4e2"

        self.root.configure(bg=self.bg_color)

        self.config = load_config()

        ensure_modpacks_dir()
        VANILLA_DIR.mkdir(parents=True, exist_ok=True)

        self.selected_modpack = StringVar()
        self.status_var = StringVar(value="Starting...")
        self.args_file_var = StringVar(value="")

        self.console_window = None
        self.console_text = None
        self.console_scroll_lock = False
        self.scroll_lock_btn = None

        self._build_ui()
        self._load_modpacks_into_list()
        self._restore_last_selection()
        self._refresh_args_file_options()

        threading.Thread(target=self._background_startup_tasks, daemon=True).start()

    def log(self, text: str, source: str = "LAUNCHER"):
        timestamp = datetime.now().strftime("%H:%M:%S")
        prefix = f"[{source}]"
        line = f"[{timestamp}] {prefix} {text}"

        if source == "LAUNCHER":
            self.status_var.set(text)

        if self.console_text is not None:
            self.console_text.config(state=NORMAL)
            self.console_text.insert(END, line + "\n")
            if not self.console_scroll_lock:
                self.console_text.see(END)
            self.console_text.config(state=DISABLED)

    def _background_startup_tasks(self):
        migrate_legacy_global_resources(self.log)
        ensure_java_runtime(self.config, self.log)
        self.log("Ready.", source="LAUNCHER")

    def _mk_main_button(self, parent, text, command):
        btn = Button(
            parent,
            text=text,
            command=command,
            bg=self.button_color,
            fg=self.text_color,
            activebackground=self.button_hover_color,
            activeforeground=self.text_color,
            relief="flat",
            padx=10,
            pady=3,
        )
        return btn

    def _build_ui(self):
        header = Frame(self.root, bg=self.panel_color, height=60)
        header.pack(fill="x", side="top")

        title_label = Label(
            header,
            text=f"{APP_NAME} v{LAUNCHER_VERSION}",
            bg=self.panel_color,
            fg=self.text_color,
            font=("Helvetica", 16, "bold"),
        )
        title_label.pack(side="left", padx=10)

        self._mk_main_button(header, "Set Minecraft Folder", self.choose_minecraft_dir).pack(
            side="right", padx=10, pady=10
        )

        main_frame = Frame(self.root, bg=self.bg_color)
        main_frame.pack(fill="both", expand=True, padx=10, pady=10)

        left_frame = Frame(main_frame, bg=self.panel_color, width=260, bd=2)
        left_frame.pack(side="left", fill="y", padx=(0, 10), pady=0)

        right_frame = Frame(main_frame, bg=self.panel_color, bd=2)
        right_frame.pack(side="right", fill="both", expand=True, pady=0)

        Label(
            left_frame,
            text="Modpacks",
            bg=self.panel_color,
            fg=self.text_color,
            font=("Helvetica", 14, "bold"),
        ).pack(anchor="w", padx=10, pady=(10, 5))

        listbox_frame = Frame(left_frame, bg=self.panel_color)
        listbox_frame.pack(fill="both", expand=True, padx=10, pady=5)

        self.modpack_listbox = Listbox(
            listbox_frame,
            bg="#1f2616",
            fg=self.text_color,
            selectbackground=self.button_color,
            selectforeground=self.text_color,
            highlightthickness=0,
            borderwidth=0,
            activestyle="none",
            font=("Helvetica", 11),
            selectmode=SINGLE,
        )
        self.modpack_listbox.pack(side="left", fill="both", expand=True)

        scrollbar = Scrollbar(listbox_frame, command=self.modpack_listbox.yview)
        scrollbar.pack(side="right", fill="y")
        self.modpack_listbox.config(yscrollcommand=scrollbar.set)
        self.modpack_listbox.bind("<<ListboxSelect>>", self._on_modpack_selected)

        mp_button_frame = Frame(left_frame, bg=self.panel_color)
        mp_button_frame.pack(fill="x", padx=10, pady=(5, 10))

        self._mk_main_button(mp_button_frame, "New", self.create_modpack_dialog).pack(
            side="left", expand=True, fill="x", padx=2
        )
        self._mk_main_button(mp_button_frame, "Edit", self.edit_modpack_dialog).pack(
            side="left", expand=True, fill="x", padx=2
        )
        self._mk_main_button(mp_button_frame, "Imp", self.import_modpack_dialog).pack(
            side="left", expand=True, fill="x", padx=2
        )
        self._mk_main_button(mp_button_frame, "Del", self.delete_modpack).pack(
            side="left", expand=True, fill="x", padx=2
        )

        details = Frame(right_frame, bg=self.panel_color)
        details.pack(fill="both", expand=True, padx=10, pady=10)

        self.details_label = Label(
            details,
            text="Select a modpack",
            bg=self.panel_color,
            fg=self.text_color,
            font=("Helvetica", 13, "bold"),
            justify="left",
        )
        self.details_label.pack(anchor="w")

        Label(
            details,
            text="Vanilla args file:",
            bg=self.panel_color,
            fg=self.text_color,
            font=("Helvetica", 10),
        ).pack(anchor="w", pady=(15, 2))

        self.args_option_menu = OptionMenu(details, self.args_file_var, "")
        self.args_option_menu.config(
            bg="#1f2616",
            fg=self.text_color,
            activebackground=self.button_hover_color,
            activeforeground=self.text_color,
            highlightthickness=0,
            borderwidth=0,
        )
        self.args_option_menu.pack(anchor="w")

        action_row = Frame(details, bg=self.panel_color)
        action_row.pack(fill="x", pady=(15, 10))

        self._mk_main_button(action_row, "Install Vanilla", self.install_vanilla_version_dialog).pack(
            side="left", padx=3
        )
        self._mk_main_button(action_row, "Console", self.open_console_window).pack(side="left", padx=3)
        self._mk_main_button(action_row, "Play", self.play).pack(side="right", padx=3)

        footer = Frame(self.root, bg=self.panel_color)
        footer.pack(fill="x", side="bottom")

        self.status_label = Label(
            footer,
            textvariable=self.status_var,
            bg=self.panel_color,
            fg=self.text_color,
            font=("Helvetica", 10),
            anchor="w",
        )
        self.status_label.pack(fill="x", padx=10, pady=6)

    def open_console_window(self):
        if self.console_window is not None and self.console_window.winfo_exists():
            self.console_window.lift()
            return

        self.console_window = Toplevel(self.root)
        self.console_window.title("The Angel Launcher Console")
        self.console_window.geometry("900x450")
        self.console_window.configure(bg="#1c2413")

        toolbar = Frame(self.console_window, bg="#2b3a1f")
        toolbar.pack(fill="x", side="top")

        Button(
            toolbar,
            text="Clear",
            command=self.console_clear,
            bg="#4d5c32",
            fg=self.text_color,
            activebackground=self.button_hover_color,
            activeforeground=self.text_color,
            relief="flat",
            padx=10,
            pady=3,
        ).pack(side="left", padx=5, pady=3)

        Button(
            toolbar,
            text="Copy",
            command=self.console_copy_all,
            bg="#4d5c32",
            fg=self.text_color,
            activebackground=self.button_hover_color,
            activeforeground=self.text_color,
            relief="flat",
            padx=10,
            pady=3,
        ).pack(side="left", padx=5, pady=3)

        Button(
            toolbar,
            text="Save",
            command=self.console_save_to_file,
            bg="#4d5c32",
            fg=self.text_color,
            activebackground=self.button_hover_color,
            activeforeground=self.text_color,
            relief="flat",
            padx=10,
            pady=3,
        ).pack(side="left", padx=5, pady=3)

        self.scroll_lock_btn = Button(
            toolbar,
            text="Scroll Lock: OFF",
            command=self.console_toggle_scroll_lock,
            bg="#4d5c32",
            fg=self.text_color,
            activebackground=self.button_hover_color,
            activeforeground=self.text_color,
            relief="flat",
            padx=10,
            pady=3,
        )
        self.scroll_lock_btn.pack(side="right", padx=5, pady=3)

        text_frame = Frame(self.console_window, bg="#1c2413")
        text_frame.pack(fill="both", expand=True)

        text_widget = Text(
            text_frame,
            bg="#101509",
            fg=self.text_color,
            insertbackground=self.text_color,
            state=DISABLED,
            wrap="none",
            font=("Consolas", 9),
        )
        text_widget.pack(side="left", fill="both", expand=True, padx=5, pady=5)

        scroll = Scrollbar(text_frame, command=text_widget.yview)
        scroll.pack(side="right", fill="y")
        text_widget.config(yscrollcommand=scroll.set)

        self.console_text = text_widget
        self.log("Console opened.", source="LAUNCHER")

        def on_close():
            self.console_window.destroy()
            self.console_window = None
            self.console_text = None

        self.console_window.protocol("WM_DELETE_WINDOW", on_close)

    def console_clear(self):
        if self.console_text is None:
            return
        self.console_text.config(state=NORMAL)
        self.console_text.delete("1.0", END)
        self.console_text.config(state=DISABLED)

    def console_copy_all(self):
        if self.console_text is None:
            return
        text = self.console_text.get("1.0", END)
        self.console_window.clipboard_clear()
        self.console_window.clipboard_append(text)

    def console_save_to_file(self):
        if self.console_text is None:
            return
        content = self.console_text.get("1.0", END)
        default_name = f"TAL_Console_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
        path = filedialog.asksaveasfilename(
            title="Save console log",
            defaultextension=".log",
            initialfile=default_name,
            filetypes=[("Log files", "*.log"), ("Text files", "*.txt"), ("All files", "*.*")],
        )
        if not path:
            return
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        self.log(f"Console log saved to {path}.", source="LAUNCHER")

    def console_toggle_scroll_lock(self):
        self.console_scroll_lock = not self.console_scroll_lock
        state = "ON" if self.console_scroll_lock else "OFF"
        if self.scroll_lock_btn:
            self.scroll_lock_btn.config(text=f"Scroll Lock: {state}")

    def _load_modpacks_into_list(self):
        self.modpack_listbox.delete(0, END)
        for name in list_modpacks():
            self.modpack_listbox.insert(END, name)

    def _restore_last_selection(self):
        last = self.config.get("last_selected_modpack") or ""
        if not last:
            return
        names = list_modpacks()
        if last not in names:
            return
        idx = names.index(last)
        self.modpack_listbox.selection_set(idx)
        self.modpack_listbox.see(idx)
        self.selected_modpack.set(last)
        self._update_details()

    def _on_modpack_selected(self, _evt=None):
        sel = self.modpack_listbox.curselection()
        if not sel:
            return
        idx = sel[0]
        name = self.modpack_listbox.get(idx)
        self.selected_modpack.set(name)
        self.config["last_selected_modpack"] = name
        save_config(self.config)
        self._update_details()

    def _update_details(self):
        name = self.selected_modpack.get() or ""
        if not name:
            self.details_label.config(text="Select a modpack")
            return

        mp_dir = MODPACKS_DIR / name
        inst = load_instance_json(mp_dir)
        mc_ver = get_instance_minecraft_version(inst)
        loader = get_instance_loader(inst)

        extra = []
        if mc_ver:
            extra.append(f"Minecraft: {mc_ver}")
        if loader:
            extra.append(f"Loader: {loader}")

        suffix = ("\n" + "\n".join(extra)) if extra else ""
        self.details_label.config(text=f"{name}{suffix}")

    def _refresh_args_file_options(self):
        VANILLA_DIR.mkdir(parents=True, exist_ok=True)
        args_files = sorted([p.name for p in VANILLA_DIR.glob("java_args_*.txt")])

        menu = self.args_option_menu["menu"]
        menu.delete(0, "end")

        if not args_files:
            self.args_file_var.set("<no args files>")
            menu.add_command(label="<no args files>", command=lambda: self._on_select_args_file("<no args files>"))
            return

        current = self.args_file_var.get()
        if current not in args_files:
            self.args_file_var.set(args_files[0])

        for name in args_files:
            menu.add_command(label=name, command=lambda v=name: self._on_select_args_file(v))

    def _on_select_args_file(self, name: str):
        self.args_file_var.set(name)

    def choose_minecraft_dir(self):
        directory = filedialog.askdirectory(title="Select your .minecraft folder or instance folder")
        if not directory:
            return
        self.config["minecraft_dir"] = directory
        save_config(self.config)
        self.log(f"Minecraft directory set to: {directory}", source="LAUNCHER")

    def create_modpack_dialog(self):
        dialog = Toplevel(self.root)
        dialog.title("Create Modpack")
        dialog.configure(bg=self.panel_color)
        dialog.grab_set()
        dialog.resizable(False, False)

        Label(dialog, text="Modpack name:", bg=self.panel_color, fg=self.text_color).pack(
            padx=10, pady=(10, 3), anchor="w"
        )

        name_var = StringVar(value="")
        Entry(dialog, textvariable=name_var, bg="#1f2616", fg=self.text_color, insertbackground=self.text_color).pack(
            padx=10, pady=3, fill="x"
        )

        def on_create():
            name = name_var.get().strip()
            if not name:
                messagebox.showwarning("Invalid name", "Please enter a modpack name.")
                return
            mp_dir = MODPACKS_DIR / name
            if mp_dir.exists():
                messagebox.showerror("Exists", "A modpack with that name already exists.")
                return

            (mp_dir / "mods").mkdir(parents=True, exist_ok=True)
            (mp_dir / "config").mkdir(parents=True, exist_ok=True)
            (mp_dir / "resourcepacks").mkdir(parents=True, exist_ok=True)

            save_instance_json(mp_dir, create_default_instance_json(name))

            dialog.destroy()
            self._load_modpacks_into_list()

        row = Frame(dialog, bg=self.panel_color)
        row.pack(fill="x", padx=10, pady=10)
        self._mk_main_button(row, "Create", on_create).pack(side="right", padx=5)
        self._mk_main_button(row, "Cancel", dialog.destroy).pack(side="right", padx=5)

    def import_modpack_dialog(self):
        archive = filedialog.askopenfilename(
            title="Import modpack",
            filetypes=[
                ("Modrinth modpack", "*.mrpack"),
                ("CurseForge modpack", "*.zip"),
                ("All files", "*.*"),
            ],
        )
        if not archive:
            return

        archive_path = Path(archive)
        default_name = archive_path.stem

        dialog = Toplevel(self.root)
        dialog.title("Import Modpack")
        dialog.configure(bg=self.panel_color)
        dialog.grab_set()
        dialog.resizable(False, False)

        Label(dialog, text="Modpack name:", bg=self.panel_color, fg=self.text_color).pack(
            padx=10, pady=(10, 3), anchor="w"
        )

        name_var = StringVar(value=default_name)
        Entry(dialog, textvariable=name_var, bg="#1f2616", fg=self.text_color, insertbackground=self.text_color).pack(
            padx=10, pady=3, fill="x"
        )

        def on_import():
            name = name_var.get().strip()
            if not name:
                messagebox.showwarning("Invalid name", "Please enter a modpack name.")
                return
            dialog.destroy()

            def worker():
                try:
                    self._do_import_modpack(archive_path, name)
                except Exception as e:
                    self.log(str(e), source="LAUNCHER")
                    self.root.after(0, lambda: messagebox.showerror("Import failed", str(e)))

            threading.Thread(target=worker, daemon=True).start()

        row = Frame(dialog, bg=self.panel_color)
        row.pack(fill="x", padx=10, pady=10)
        self._mk_main_button(row, "Import", on_import).pack(side="right", padx=5)
        self._mk_main_button(row, "Cancel", dialog.destroy).pack(side="right", padx=5)

    def _do_import_modpack(self, archive_path: Path, name: str):
        mp_dir = MODPACKS_DIR / name
        if mp_dir.exists():
            raise RuntimeError("A modpack with that name already exists.")

        mp_dir.mkdir(parents=True, exist_ok=True)
        (mp_dir / "mods").mkdir(parents=True, exist_ok=True)
        (mp_dir / "config").mkdir(parents=True, exist_ok=True)
        (mp_dir / "resourcepacks").mkdir(parents=True, exist_ok=True)

        instance = create_default_instance_json(name)
        launcher = instance.get("launcher") or {}
        lv = launcher.get("loaderVersion") or {}

        suffix = archive_path.suffix.lower()
        if suffix == ".mrpack":
            self.log(f"Importing Modrinth modpack: {archive_path.name}", source="LAUNCHER")
            index = import_modrinth_modpack(archive_path, mp_dir, self.log)

            deps = (index or {}).get("dependencies") or {}
            mc = deps.get("minecraft")
            if isinstance(mc, str) and mc:
                lv["rawVersion"] = mc

            if "neoforge" in deps:
                lv["type"] = "neoforge"
                if mc:
                    lv["rawVersion"] = f"{mc}-{deps['neoforge']}"
            elif "forge" in deps:
                lv["type"] = "forge"
                if mc:
                    lv["rawVersion"] = f"{mc}-{deps['forge']}"
            elif "fabric-loader" in deps:
                lv["type"] = "fabric"
                if mc:
                    lv["rawVersion"] = f"{mc}-{deps['fabric-loader']}"
            elif "quilt-loader" in deps:
                lv["type"] = "quilt"
                if mc:
                    lv["rawVersion"] = f"{mc}-{deps['quilt-loader']}"

        elif suffix == ".zip":
            self.log(f"Importing CurseForge modpack: {archive_path.name}", source="LAUNCHER")
            manifest = import_curseforge_modpack(archive_path, mp_dir)

            mc = ((manifest or {}).get("minecraft") or {}).get("version")
            if isinstance(mc, str) and mc:
                lv["rawVersion"] = mc

            modloaders = ((manifest or {}).get("minecraft") or {}).get("modLoaders") or []
            if modloaders:
                mid = (modloaders[0] or {}).get("id")
                if isinstance(mid, str) and "-" in mid:
                    loader_name, loader_ver = mid.split("-", 1)
                    lv["type"] = normalize_loader_name(loader_name)
                    if mc:
                        lv["rawVersion"] = f"{mc}-{loader_ver}"
        else:
            raise RuntimeError("Unsupported modpack format. Use .mrpack or .zip")

        launcher["loaderVersion"] = lv
        instance["launcher"] = launcher
        save_instance_json(mp_dir, instance)

        def update_ui():
            self._load_modpacks_into_list()
            names = list_modpacks()
            if name in names:
                idx = names.index(name)
                self.modpack_listbox.selection_clear(0, END)
                self.modpack_listbox.selection_set(idx)
                self.modpack_listbox.see(idx)
                self.selected_modpack.set(name)
                self.config["last_selected_modpack"] = name
                save_config(self.config)
                self._update_details()

        self.root.after(0, update_ui)

    def edit_modpack_dialog(self):
        name = self.selected_modpack.get()
        if not name:
            messagebox.showinfo("No modpack", "Select a modpack first.")
            return

        mp_dir = MODPACKS_DIR / name
        if not mp_dir.exists():
            messagebox.showerror("Missing", f"Modpack folder missing: {mp_dir}")
            return

        inst = load_instance_json(mp_dir)
        if inst is None:
            inst = create_default_instance_json(name)
            save_instance_json(mp_dir, inst)

        launcher = inst.get("launcher") or {}
        lv = launcher.get("loaderVersion") or {}

        dialog = Toplevel(self.root)
        dialog.title(f"Edit Modpack: {name}")
        dialog.configure(bg=self.panel_color)
        dialog.grab_set()
        dialog.geometry("720x460")

        top = Frame(dialog, bg=self.panel_color)
        top.pack(fill="x", padx=10, pady=10)

        Label(top, text="Minecraft version:", bg=self.panel_color, fg=self.text_color).grid(row=0, column=0, sticky="w")
        mc_var = StringVar(value=get_instance_minecraft_version(inst) or "")
        Entry(top, textvariable=mc_var, bg="#1f2616", fg=self.text_color, insertbackground=self.text_color).grid(
            row=0, column=1, sticky="we", padx=(8, 0)
        )

        Label(top, text="Loader:", bg=self.panel_color, fg=self.text_color).grid(row=1, column=0, sticky="w", pady=(6, 0))
        loader_choices = ["", "forge", "fabric", "quilt", "neoforge"]
        loader_var = StringVar(value=normalize_loader_name(lv.get("type") or ""))
        OptionMenu(top, loader_var, *loader_choices).grid(row=1, column=1, sticky="w", padx=(8, 0), pady=(6, 0))

        Label(top, text="Max memory (MB):", bg=self.panel_color, fg=self.text_color).grid(row=2, column=0, sticky="w", pady=(6, 0))
        max_mem_var = StringVar(value=str((launcher.get("maximumMemory") or 4096)))
        Entry(top, textvariable=max_mem_var, bg="#1f2616", fg=self.text_color, insertbackground=self.text_color).grid(
            row=2, column=1, sticky="we", padx=(8, 0), pady=(6, 0)
        )

        Label(top, text="Min memory (MB):", bg=self.panel_color, fg=self.text_color).grid(row=3, column=0, sticky="w", pady=(6, 0))
        min_mem_var = StringVar(value=str((launcher.get("requiredMemory") or 0)))
        Entry(top, textvariable=min_mem_var, bg="#1f2616", fg=self.text_color, insertbackground=self.text_color).grid(
            row=3, column=1, sticky="we", padx=(8, 0), pady=(6, 0)
        )

        Label(top, text="Extra JVM args:", bg=self.panel_color, fg=self.text_color).grid(row=4, column=0, sticky="w", pady=(6, 0))
        extra_var = StringVar(value=str(launcher.get("additionalJvmArgs") or ""))
        Entry(top, textvariable=extra_var, bg="#1f2616", fg=self.text_color, insertbackground=self.text_color).grid(
            row=4, column=1, sticky="we", padx=(8, 0), pady=(6, 0)
        )

        top.columnconfigure(1, weight=1)

        mid = Frame(dialog, bg=self.panel_color)
        mid.pack(fill="both", expand=True, padx=10, pady=(0, 10))

        Label(mid, text="Mods:", bg=self.panel_color, fg=self.text_color, font=("Helvetica", 11, "bold")).pack(anchor="w")

        mods_list = Listbox(
            mid,
            bg="#1f2616",
            fg=self.text_color,
            selectbackground=self.button_color,
            selectforeground=self.text_color,
            highlightthickness=0,
            borderwidth=0,
            activestyle="none",
            font=("Helvetica", 10),
        )
        mods_list.pack(fill="both", expand=True, pady=5)

        mods_dir = mp_dir / "mods"
        mods_dir.mkdir(parents=True, exist_ok=True)
        for p in sorted(mods_dir.glob("*.jar")):
            mods_list.insert(END, p.name)

        btn_row = Frame(mid, bg=self.panel_color)
        btn_row.pack(fill="x")

        def on_remove_selected():
            sel = mods_list.curselection()
            if not sel:
                return
            fname = mods_list.get(sel[0])
            try:
                (mods_dir / fname).unlink()
            except OSError:
                pass
            mods_list.delete(sel[0])

        self._mk_main_button(btn_row, "Add Mod", lambda: self.add_mod_dialog(mp_dir, mods_list)).pack(side="left", padx=3)
        self._mk_main_button(btn_row, "Remove", on_remove_selected).pack(side="left", padx=3)

        bottom = Frame(dialog, bg=self.panel_color)
        bottom.pack(fill="x", padx=10, pady=(0, 10))

        def on_save():
            launcher = inst.get("launcher") or {}
            lv = launcher.get("loaderVersion") or {}

            mc = mc_var.get().strip()
            loader = loader_var.get().strip()

            try:
                max_mem = int(max_mem_var.get().strip())
            except ValueError:
                max_mem = 4096

            try:
                min_mem = int(min_mem_var.get().strip())
            except ValueError:
                min_mem = 0

            lv["type"] = loader
            launcher["loaderVersion"] = lv
            launcher["maximumMemory"] = max_mem
            launcher["requiredMemory"] = min_mem
            launcher["additionalJvmArgs"] = extra_var.get()

            if mc:
                lv["rawVersion"] = mc

            inst["launcher"] = launcher
            save_instance_json(mp_dir, inst)

            dialog.destroy()
            self._update_details()

        self._mk_main_button(bottom, "Save", on_save).pack(side="right", padx=5)
        self._mk_main_button(bottom, "Close", dialog.destroy).pack(side="right", padx=5)

    def delete_modpack(self):
        name = self.selected_modpack.get()
        if not name:
            messagebox.showinfo("No modpack", "Select a modpack first.")
            return
        mp_dir = MODPACKS_DIR / name
        if not mp_dir.exists():
            return
        if not messagebox.askyesno("Delete", f"Delete modpack '{name}'? This removes {mp_dir}."):
            return
        shutil.rmtree(mp_dir)
        self.selected_modpack.set("")
        self._load_modpacks_into_list()
        self._update_details()

    def install_vanilla_version_dialog(self):
        dialog = Toplevel(self.root)
        dialog.title("Install Vanilla Version")
        dialog.configure(bg=self.panel_color)
        dialog.grab_set()
        dialog.resizable(False, False)

        Label(
            dialog,
            text="Minecraft Version ID (e.g. 1.21.1):",
            bg=self.panel_color,
            fg=self.text_color,
            font=("Helvetica", 11),
        ).pack(padx=10, pady=(10, 3), anchor="w")

        version_var = StringVar(value="1.21.1")
        entry = Entry(
            dialog,
            textvariable=version_var,
            bg="#1f2616",
            fg=self.text_color,
            insertbackground=self.text_color,
        )
        entry.pack(padx=10, pady=3, fill="x")
        entry.focus_set()

        def on_install():
            version_id = version_var.get().strip()
            if not version_id:
                messagebox.showwarning("Invalid version", "Please enter a version ID.")
                return
            dialog.destroy()
            threading.Thread(target=self._do_install_vanilla_version, args=(version_id,), daemon=True).start()

        btn_frame = Frame(dialog, bg=self.panel_color)
        btn_frame.pack(padx=10, pady=10, fill="x")

        self._mk_main_button(btn_frame, "Install", on_install).pack(side="right", padx=5)
        self._mk_main_button(btn_frame, "Cancel", dialog.destroy).pack(side="right", padx=5)

    def _do_install_vanilla_version(self, version_id: str):
        try:
            args_file = download_vanilla_version(version_id, self.config, self.log)
            self._refresh_args_file_options()
            self._on_select_args_file(args_file.name)
        except Exception as e:
            messagebox.showerror("Install error", f"Failed to install vanilla {version_id}:\n{e}")
            self.log("Failed to install vanilla version.", source="LAUNCHER")

    def add_mod_dialog(self, mp_dir: Path, mods_list: Listbox):
        inst = load_instance_json(mp_dir)
        target_mc_version = get_instance_minecraft_version(inst) or infer_minecraft_version_from_args_filename(self.args_file_var.get())
        target_loader = get_instance_loader(inst)

        dialog = Toplevel(self.root)
        dialog.title("Add Mod")
        dialog.configure(bg=self.panel_color)
        dialog.grab_set()
        dialog.resizable(False, False)

        Label(dialog, text="Source:", bg=self.panel_color, fg=self.text_color).pack(padx=10, pady=(10, 3), anchor="w")
        source_var = StringVar(value="Modrinth")
        OptionMenu(dialog, source_var, "Modrinth", "CurseForge").pack(padx=10, pady=3, anchor="w")

        Label(dialog, text="Project URL / slug / id:", bg=self.panel_color, fg=self.text_color).pack(
            padx=10, pady=(8, 3), anchor="w"
        )
        text_var = StringVar(value="")
        Entry(dialog, textvariable=text_var, bg="#1f2616", fg=self.text_color, insertbackground=self.text_color).pack(
            padx=10, pady=3, fill="x"
        )

        hint = f"Target MC: {target_mc_version or 'unknown'} | Loader: {target_loader or 'any'}"
        Label(dialog, text=hint, bg=self.panel_color, fg=self.text_color, font=("Helvetica", 9)).pack(
            padx=10, pady=(0, 8), anchor="w"
        )

        def on_add():
            txt = text_var.get().strip()
            if not txt:
                messagebox.showwarning("Missing", "Enter a URL/slug/id.")
                return
            dialog.destroy()

            def worker():
                try:
                    mods_dir = mp_dir / "mods"
                    mods_dir.mkdir(parents=True, exist_ok=True)

                    if source_var.get() == "Modrinth":
                        mr.add_mod(txt, mods_dir, self.log, target_mc_version, target_loader)
                    else:
                        cf.add_mod(txt, mods_dir, self.log, target_mc_version, target_loader)

                    self.root.after(0, lambda: self._reload_mods_list(mods_list, mods_dir))
                except Exception as e:
                    self.log(str(e), source="LAUNCHER")
                    self.root.after(0, lambda: messagebox.showerror("Add mod failed", str(e)))

            threading.Thread(target=worker, daemon=True).start()

        btn = Frame(dialog, bg=self.panel_color)
        btn.pack(fill="x", padx=10, pady=10)
        self._mk_main_button(btn, "Add", on_add).pack(side="right", padx=5)
        self._mk_main_button(btn, "Cancel", dialog.destroy).pack(side="right", padx=5)

    def _reload_mods_list(self, mods_list: Listbox, mods_dir: Path):
        mods_list.delete(0, END)
        for p in sorted(mods_dir.glob("*.jar")):
            mods_list.insert(END, p.name)

    def play(self):
        name = self.selected_modpack.get()
        if not name:
            messagebox.showinfo("No modpack", "Please select a modpack first.")
            return

        mc_dir = self.config.get("minecraft_dir") or ""
        if not mc_dir or not os.path.isdir(mc_dir):
            messagebox.showerror("Minecraft folder not set", "Please set your .minecraft folder first.")
            return

        mp_dir = MODPACKS_DIR / name
        if not mp_dir.exists():
            messagebox.showerror("Missing modpack", f"Modpack folder missing: {mp_dir}")
            return

        inst = load_instance_json(mp_dir)
        if inst is None:
            inst = create_default_instance_json(name)
            save_instance_json(mp_dir, inst)

        launcher_cfg = inst.get("launcher") or {}
        max_mem = launcher_cfg.get("maximumMemory")
        min_mem = launcher_cfg.get("requiredMemory")
        extra_jvm = launcher_cfg.get("additionalJvmArgs")

        try:
            max_mem = int(max_mem) if max_mem else None
        except (TypeError, ValueError):
            max_mem = None
        try:
            min_mem = int(min_mem) if min_mem else None
        except (TypeError, ValueError):
            min_mem = None
        if min_mem == 0:
            min_mem = None

        if not isinstance(extra_jvm, str):
            extra_jvm = ""

        java_exe = get_java_executable()
        if sys.platform.startswith("win") and not java_exe.exists():
            messagebox.showerror("Java not found", f"Bundled Java not found at:\n{java_exe}")
            return

        args_name = self.args_file_var.get()
        if args_name.startswith("<no args"):
            messagebox.showerror("No args", "No vanilla args files found. Install vanilla first.")
            return

        args_file = VANILLA_DIR / args_name
        if not args_file.exists():
            messagebox.showerror("Args missing", f"Args file not found:\n{args_file}")
            return

        self.open_console_window()
        self.log(f"Applying modpack '{name}'...", source="LAUNCHER")

        mods_src = mp_dir / "mods"
        mods_dst = Path(mc_dir) / "mods"
        mods_dst.mkdir(parents=True, exist_ok=True)
        clean_dir(str(mods_dst))
        copy_tree(str(mods_src), str(mods_dst))

        config_src = mp_dir / "config"
        config_dst = Path(mc_dir) / "config"
        config_dst.mkdir(parents=True, exist_ok=True)
        copy_tree(str(config_src), str(config_dst))

        res_src = mp_dir / "resourcepacks"
        res_dst = Path(mc_dir) / "resourcepacks"
        res_dst.mkdir(parents=True, exist_ok=True)
        copy_tree(str(res_src), str(res_dst))

        self._launch_with_argfile(java_exe, args_file, max_mem=max_mem, min_mem=min_mem, extra_jvm=extra_jvm)

    def _launch_with_argfile(self, java_exe: Path, args_file: Path, max_mem=None, min_mem=None, extra_jvm: str = ""):
        try:
            rel_args_path = args_file.relative_to(INSTALL_DIR)
        except ValueError:
            rel_args_path = Path("vanilla") / args_file.name

        argfile_arg = f"@{rel_args_path.as_posix()}"

        cmd = [str(java_exe)]

        if extra_jvm.strip():
            extra_args = shlex.split(extra_jvm, posix=not sys.platform.startswith("win"))
            cmd.extend(extra_args)

        if max_mem:
            cmd.append(f"-Xmx{max_mem}M")
        if min_mem:
            cmd.append(f"-Xms{min_mem}M")

        cmd.append(argfile_arg)

        try:
            if sys.platform.startswith("win"):
                cmd_str = subprocess.list2cmdline(cmd)
            else:
                cmd_str = shlex.join(cmd)
            self.log(f"Launch command: {cmd_str}", source="LAUNCHER")
        except Exception:
            self.log(f"Launch command: {cmd}", source="LAUNCHER")

        proc = subprocess.Popen(
            cmd,
            cwd=str(INSTALL_DIR),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
        )

        def reader_thread():
            assert proc.stdout is not None
            for line in proc.stdout:
                line = line.rstrip("\n\r")
                if line:
                    self.log(line, source="GAME")

        threading.Thread(target=reader_thread, daemon=True).start()


def main():
    root = Tk()
    app = MinecraftLauncherApp(root)
    root.mainloop()
