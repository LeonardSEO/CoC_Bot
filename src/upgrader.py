from utils import *
try:
    import configs
    from configs import *
except:
    import configs_build as configs
    from configs_build import *

class Upgrader:
    def __init__(self, decisions=None):
        self.assets = Asset_Manager.upgrader_assets
        self.misc_assets = Asset_Manager.misc_assets
        if decisions is None:
            from jev.runtime import create_service
            decisions = create_service(configs)
        self.decisions = decisions
        self._pending_jev_upgrade = None
        self._jev_availability = {'builders': None, 'lab_available': None}

    def _choose_jev_upgrade(self, locations, legacy, menu_left, menu_right, context, discounted=False):
        try:
            return self._observe_jev_upgrade(locations, legacy, menu_left, menu_right, context, discounted)
        except (KeyboardInterrupt, SystemExit):
            raise
        except Exception:
            self._pending_jev_upgrade = None
            self.decisions.record('fallback', kind='upgrade', reason='upgrade_observation_error')
            return legacy

    def _observe_jev_upgrade(self, locations, legacy, menu_left, menu_right, context, discounted=False):
        """Observe existing locator results without adding menu clicks or scrolls."""
        import re, time
        from jev.upgrades import UpgradeCandidate, choose_upgrade
        settings = self.decisions.settings
        if settings.mode == 'off' or not settings.upgrades or len(locations) < 2:
            return legacy
        observed_at = time.time()
        known = set()
        for values in Cache_Manager.get('vocab', {}).values():
            known.update(values)
        for key in ('HOME_BASE_UPGRADE_PRIORITY', 'HOME_LAB_UPGRADE_PRIORITY', 'BUILDER_BASE_UPGRADE_PRIORITY', 'BUILDER_LAB_UPGRADE_PRIORITY'):
            for group in getattr(configs, key, []):
                known.update(group)
        canonical = {name.lower(): name for name in known}
        rows = []
        for location in locations:
            x, y = location[:2]
            name = location[2] if len(location) > 2 else None
            if name is None:
                section = Frame_Handler.get_frame_section(menu_left, y-.025, (menu_left+menu_right)/2, y+.025, high_contrast=True, use_cached=True)
                texts = OCR_Handler.get_text(section)
                cleaned = [re.sub(r'\s*x\d+$', '', text.strip().lower()) for text in texts]
                name = next((canonical[text] for text in cleaned if text in canonical), None)
            rows.append(UpgradeCandidate(name or 'unknown', float(x), float(y), discounted=discounted, quality=.8 if name else 0, observed_at=observed_at))
        legacy_row = next((row for row in rows if abs(row.y-legacy[1]) < .001), None)
        if legacy_row is None:
            return legacy
        availability = self._jev_availability.copy()
        selected = choose_upgrade(self.decisions, rows, legacy_row, context, availability)
        if settings.mode != 'active' or any(row.quality < settings.min_quality for row in rows):
            return legacy
        # Reacquire the name at the chosen row; old menu coordinates never suffice.
        frame = Frame_Handler.get_frame(grayscale=False)
        section = Frame_Handler.crop(frame, menu_left, selected.y-.025, menu_right, selected.y+.025)
        template = render_text(selected.name, 'CCBackBeat', 27)
        x, y = Frame_Handler.locate(template, section, ref='lc', thresh=.80)
        if x is None or y is None or check_color((255, 136, 127), section, tol=10):
            self.decisions.record('fallback', kind='upgrade', reason='chosen_row_changed')
            return (None, None, None) if len(legacy) > 2 else (None, None)
        self._pending_jev_upgrade = {'name': selected.name, 'context': context,
            'hero': selected.name.lower() in [name.lower() for name in Cache_Manager.get('vocab', {}).get('heroes', [])]}
        return (selected.x, selected.y, selected.name) if len(legacy) > 2 else (selected.x, selected.y)

    def _jev_confirmation_name(self, frame):
        """Read an anchored dialog title exactly; fuzzy vocabulary is not proof."""
        import re
        x, y = Frame_Handler.locate(self.assets['upgrade_name'], frame=frame, ref='lc', thresh=.9)
        if x is None or y is None:
            return None
        section = Frame_Handler.crop(frame, x+.122, y-.04, 1-x, y+.035)
        texts = OCR_Handler.get_text(Frame_Handler.high_contrast(section, thresh=255))
        name = ' '.join(texts).strip().lower()
        name = re.sub(r'\s*x\d+$', '', name)
        name = re.sub(r'\s+(?:to\s+)?(?:level\s*)?\(?\d+\)?\s*$', '', name)
        return name

    def _verify_jev_confirmation(self, frame=None):
        pending = self._pending_jev_upgrade
        if pending is None:
            return True
        context = pending['context']
        if Task_Handler.excluded(context) or (pending.get('hero') and Task_Handler.excluded('heroes')):
            self.decisions.record('fallback', kind='upgrade', reason='excluded_before_confirmation')
            return False
        try:
            if frame is None: frame = Frame_Handler.get_frame(grayscale=False)
            actual = self._jev_confirmation_name(frame)
            matches = actual is not None and actual.strip().lower() == pending['name'].strip().lower()
            if not matches:
                self.decisions.record('fallback', kind='upgrade', reason='confirmation_name_mismatch')
            return matches
        except (KeyboardInterrupt, SystemExit):
            raise
        except Exception:
            self.decisions.record('fallback', kind='upgrade', reason='confirmation_unreadable')
            return False

    # ============================================================
    # 📱 Screen Interaction
    # ============================================================
    
    def _click_home_builders(self):
        Input_Handler.click(0.5, 0.05)
    
    def _click_home_lab(self):
        Input_Handler.click(0.4, 0.05)

    def _click_builder_builders(self):
        Input_Handler.click(0.6, 0.05)
    
    def _click_builder_lab(self):
        Input_Handler.click(0.45, 0.05)

    def _click_upgrade(self, timeout=5):
        return click_with_timeout(
            lambda: Frame_Handler.locate(self.assets["upgrade"], thresh=0.90, grayscale=False),
            timeout=timeout
        )

    def _click_home_confirm(self, timeout=5):
        if self._pending_jev_upgrade is None:
            return click_with_timeout(lambda: Frame_Handler.locate(self.assets['confirm'], grayscale=False, thresh=.85, use_cached=True), timeout=timeout)
        def locate():
            frame = Frame_Handler.get_frame(grayscale=False)
            if not self._verify_jev_confirmation(frame): return None, None
            return Frame_Handler.locate(self.assets['confirm'], frame=frame, grayscale=False, thresh=.85)
        try:
            return click_with_timeout(locate, timeout=timeout)
        finally:
            self._pending_jev_upgrade = None

    def _click_builder_confirm(self, timeout=5):
        if self._pending_jev_upgrade is None:
            return click_with_timeout(lambda: self._find_builder_confirm(), timeout=timeout)
        def locate():
            frame = Frame_Handler.get_frame(grayscale=False)
            if not self._verify_jev_confirmation(frame): return None, None
            return self._find_builder_confirm(frame=frame)
        try:
            return click_with_timeout(locate, timeout=timeout)
        finally:
            self._pending_jev_upgrade = None

    def _scroll_to_menu_bottom(self, menu_left, menu_right, menu_top, menu_bottom, max_scrolls=10):
        import numpy as np
        menu_center = (menu_left + menu_right) / 2
        for _ in range(max_scrolls):
            menu_prev = Frame_Handler.get_frame_section(menu_left, menu_top, menu_right, menu_bottom, high_contrast=True)
            Input_Handler.swipe_up(x=menu_center, y1=menu_bottom-0.05, y2=0.15, duration=0, hold_end_time=0, inter_points=10)
            menu_curr = Frame_Handler.get_frame_section(menu_left, menu_top, menu_right, menu_bottom, high_contrast=True)
            diff = np.abs(menu_curr - menu_prev).mean() / 255
            if diff < 0.01: break

    # ============================================================
    # 💰 Resource & Builder Tracking
    # ============================================================

    def home_lab_available(self, timeout=60):
        import time, cv2
        
        start = time.time()
        while time.time() < start + timeout:
            try:
                section = Frame_Handler.get_frame_section(0.368, 0.04, -0.59, 0.08, high_contrast=True)
                if configs.DEBUG: Frame_Handler.save_frame(section, "home_lab.png")
                
                # Find the backslash
                slash = cv2.cvtColor(self.misc_assets["slash"], cv2.COLOR_RGB2GRAY)
                res = cv2.matchTemplate(section, slash, cv2.TM_CCOEFF_NORMED)
                _, max_val, _, _ = cv2.minMaxLoc(res)
                if max_val < 0.9: continue
                
                # Extract text
                text = fix_digits(''.join(OCR_Handler.get_text(section)).replace(' ', '').replace('/', ''))
                if not text or not text[0].isdigit():
                    raise AutomationStopped('Lab count unreadable; refusing upgrade inputs')
                available = int(text[0])
                return available > 0
            except (KeyboardInterrupt, SystemExit): raise
            except Exception as e:
                logger.error(f"Upgrader.home_lab_available: {e}")
            time.sleep(0.5)
        raise Exception("Failed to get home lab availability")

    def builder_lab_available(self, timeout=60):
        import time, cv2
        
        start = time.time()
        while time.time() < start + timeout:
            try:
                section = Frame_Handler.get_frame_section(0.45, 0.04, -0.505, 0.08, high_contrast=True)
                if configs.DEBUG: Frame_Handler.save_frame(section, "builder_lab.png")
                
                # Find the backslash
                slash = cv2.cvtColor(self.misc_assets["slash"], cv2.COLOR_RGB2GRAY)
                res = cv2.matchTemplate(section, slash, cv2.TM_CCOEFF_NORMED)
                _, max_val, _, _ = cv2.minMaxLoc(res)
                if max_val < 0.9: continue
                
                # Extract text
                text = fix_digits(''.join(OCR_Handler.get_text(section)).replace(' ', '').replace('/', ''))
                if not text or not text[0].isdigit():
                    raise AutomationStopped('Builder lab count unreadable; refusing upgrade inputs')
                available = int(text[0])
                return available > 0
            except (KeyboardInterrupt, SystemExit): raise
            except Exception as e:
                logger.error(f"Upgrader.builder_lab_available: {e}")
            time.sleep(0.5)
        raise Exception("Failed to get builder lab availability")

    def collect_builder_attack_elixir(self):
        import time
        
        # Align view to top right corner
        Input_Handler.zoom(dir="out")
        for _ in range(3):
            Input_Handler.swipe_up(
                y1=0.5,
                y2=1.0,
            )
        Input_Handler.swipe_up(
            y1=0.5,
            y2=1.0,
            hold_end_time=500,
        )
        for _ in range(3):
            Input_Handler.swipe_left(
                x1=1.0,
                x2=0.0,
            )
        Input_Handler.swipe_left(
            x1=1.0,
            x2=0.0,
            hold_end_time=500,
        )
        time.sleep(0.5)
        
        # Open elixir cart menu
        Input_Handler.click(0.61, 0.47)
        time.sleep(0.5)
        
        # Collect elixir
        x, y = Frame_Handler.locate(self.assets["collect"], grayscale=False, thresh=0.9)
        if x is not None and y is not None:
            Input_Handler.click(x, y)
            time.sleep(0.1)
        Input_Handler.click_exit(5, 0.1)

    # ============================================================
    # 🧱 Upgrade Management
    # ============================================================

    def _get_suggested_upgrade_template(self):
        template = render_text("Suggested upgrades:", "CCBackBeat", 27, color=(211, 253, 127))
        h, w = template.shape[:2]
        return template, w / WINDOW_DIMS[0], h / WINDOW_DIMS[1]

    def _get_other_upgrade_template(self):
        template = render_text("Other upgrades:", "CCBackBeat", 27, color=(211, 253, 127))
        h, w = template.shape[:2]
        return template, w / WINDOW_DIMS[0], h / WINDOW_DIMS[1]

    def _get_upgrade_name(self, categories=["all"]):
        import re
        x, y = Frame_Handler.locate(self.assets["upgrade_name"], ref="lc", thresh=0.9)
        section = Frame_Handler.get_frame_section(x+0.122, y-0.04, 1-x, y+0.035, high_contrast=True, thresh=255, use_cached=True)
        if configs.DEBUG: Frame_Handler.save_frame(section, "upgrade_name.png")
        upgrade_name = spell_check(re.sub(r"\s*x\d+$", "", OCR_Handler.get_text(section)[0].lower()[:-3]), categories, phrase_level=True)
        return upgrade_name

    def _get_upgrade_menu(self, frame, sug_loc, sug_width, return_bounds=False):
        x_sug, y_sug = sug_loc
        menu_top = 0.15
        menu_left = x_sug - 0.5*sug_width
        menu_right = x_sug + 0.5*sug_width + 0.11
        menu = Frame_Handler.crop(frame, menu_left, y_sug, menu_right, 1.0)
        menu_high_contrast = Frame_Handler.high_contrast(menu, thresh=255) / 255
        menu_bottom = y_sug + menu_high_contrast.mean(axis=1).argmax() / WINDOW_DIMS[1]
        menu = Frame_Handler.crop(frame, menu_left, menu_top, menu_right, menu_bottom)
        if return_bounds: return menu, menu_left, menu_top, menu_right, menu_bottom
        return menu

    def _get_potential_upgrade_locs(self, menu):
        import numpy as np
        
        def profile_bounds(profile):
            bounds = []
            prev_val = 0
            for i, val in enumerate(profile):
                if prev_val == 0 and val == 1:
                    bounds.append(i)
                if prev_val == 1 and val == 0:
                    bounds.append(i)
                prev_val = val
            if prev_val == 1:
                bounds.append(len(profile))
            bounds = np.array(bounds).reshape((-1, 2))
            centers = (bounds[:, 0] + bounds[:, 1]) / 2
            return bounds, centers
        
        menu_white = (filter_color([255, 255, 255], menu, tol=0, return_mask=True)[1])
        menu_red = filter_color((255, 136, 127), menu, tol=10, return_mask=True)[1]
        white_profile = np.where(menu_white.mean(axis=1) > 0.01, 1, 0)
        red_profile = np.where(menu_red.mean(axis=1) > 0.01, 1, 0)
        white_bounds, white_centers = profile_bounds(white_profile)
        red_bounds, red_centers = profile_bounds(red_profile)
        potential_y_locs = [] # in pixels
        for wc in white_centers:
            if len(red_centers) == 0 or abs(red_centers - wc).min() > 12.5:
                potential_y_locs.append(wc)
        return np.array(potential_y_locs)

    def _find_builder_confirm(self, frame=None):
        import cv2, numpy as np
        from scipy.ndimage import gaussian_filter1d
        thresh = 0.2
        section = Frame_Handler.get_frame_section(0.0, 0.9, 1.0, 0.92, grayscale=False) if frame is None else Frame_Handler.crop(frame, 0.0, 0.9, 1.0, 0.92)
        section = cv2.cvtColor(section, cv2.COLOR_RGB2LAB).astype(np.float32)
        btn_color = cv2.cvtColor(np.array([[[189, 230, 76]]], dtype=np.uint8), cv2.COLOR_RGB2LAB).astype(np.float32)
        diff = np.linalg.norm((section - btn_color)/255, axis=2).mean(0)
        diff = gaussian_filter1d(diff, sigma=10)
        min_loc = np.argmin(diff)
        x = min_loc / section.shape[1]
        if diff[min_loc] > thresh: return None, None
        x1 = x
        i = min_loc
        while i > 0 and diff[i] < thresh:
            x1 = i / section.shape[1]
            i -= 1
        x2 = x
        i = min_loc
        while i < section.shape[1]-1 and diff[i] < thresh:
            x2 = i / section.shape[1]
            i += 1
        x = (x1 + x2) / 2
        y = 0.85
        return x, y
    
    def _scroll_locate_upgrade(self, locate_func, menu_left, menu_right, menu_top, menu_bottom, dir="down"):
        # First two return values of locate_func should be x and y of located upgrade
        import time, numpy as np
        menu_center = (menu_left + menu_right) / 2
        res = locate_func()
        if res[0] is None or res[1] is None:
            prev_section = Frame_Handler.get_frame_section(menu_left, menu_top, menu_right, menu_bottom, high_contrast=True, thresh=255)
            for _ in range(20):
                if dir == "down":
                    y1, y2 = menu_bottom-0.05, menu_top+0.05
                elif dir == "up":
                    y1, y2 = menu_top+0.05, menu_bottom-0.05
                Input_Handler.swipe(x1=menu_center, y1=y1, x2=menu_center, y2=y2, duration=0, hold_end_time=100, inter_points=10)
                time.sleep(0.1)
                
                # Check if at end of upgrade menu
                section = Frame_Handler.get_frame_section(menu_left, menu_top, menu_right, menu_bottom, high_contrast=True, thresh=255)
                diff = np.abs(section - prev_section).mean() / 255
                if diff < 0.01: break
                prev_section = section
                
                res = locate_func()
                if res[0] is not None and res[1] is not None: break
        return res
    
    @require_exit()
    def home_random_upgrade(self):
        import time, numpy as np

        self._pending_jev_upgrade = None

        try:
            # Open upgrade list menu
            self._click_home_builders()
            time.sleep(0.5)
            
            # Locate menu boundaries
            sug_template, sug_width, sug_height = self._get_suggested_upgrade_template()
            x_sug, y_sug = Frame_Handler.locate(sug_template, thresh=0.70, grayscale=False)
            if x_sug is None or y_sug is None: return None
            frame = Frame_Handler.get_frame(grayscale=False, use_cached=True)
            menu, menu_left, menu_top, menu_right, menu_bottom = self._get_upgrade_menu(frame, (x_sug, y_sug), sug_width, return_bounds=True)
            menu_center = (menu_left + menu_right) / 2
            if configs.START_FROM_MENU_TOP:
                Input_Handler.swipe_up(x=menu_center, y1=y_sug, y2=0.15, duration=0, hold_end_time=100, inter_points=10)
            else:
                self._scroll_to_menu_bottom(menu_left, menu_right, menu_top, menu_bottom)
            
            town_hall_template = [render_text("Town Hall", "CCBackBeat", 27)]
            hero_templates = [render_text(text, "CCBackBeat", 27) for text in Cache_Manager.get("vocab", get_vocab())["heroes"]]
            seasonal_defense_templates = [render_text(text, "CCBackBeat", 27) for text in Cache_Manager.get("vocab", get_vocab())["buildings/seasonal-defense"]]
            heros_excluded = Task_Handler.excluded("heroes")
            
            def locate_upgrade():
                frame = Frame_Handler.get_frame(grayscale=False)
                menu = Frame_Handler.crop(frame, menu_left, menu_top, menu_right, menu_bottom)
                x_sug, y_sug = Frame_Handler.locate(sug_template, frame, thresh=0.70, grayscale=False)

                # Find a valid upgrade
                potential_y_locs = self._get_potential_upgrade_locs(menu)
                if len(potential_y_locs) == 0: return None, None
                potential_y_locs = potential_y_locs / WINDOW_DIMS[1] + menu_top
                if y_sug is not None: potential_y_locs = potential_y_locs[potential_y_locs > y_sug]
                
                # Locate invalid upgrades
                invalid_templates = town_hall_template + hero_templates + seasonal_defense_templates
                locs = Frame_Handler.batch_locate(invalid_templates, menu, thresh=0.75, ref="lc", null_val=-1, grayscale=True, normalize=False, return_all=True)
                town_hall_loc, hero_locs, seasonal_defense_locs = chunk_list(locs, [1, len(hero_templates), len(seasonal_defense_templates)])
                flat_seasonal_defense_locs = []
                for locs in seasonal_defense_locs: flat_seasonal_defense_locs += locs
                invalid_locs = town_hall_loc[0] + flat_seasonal_defense_locs
                town_hall_loc = town_hall_loc[0]
                if heros_excluded:
                    for locs in hero_locs: invalid_locs += locs
                invalid_y_locs = np.array(invalid_locs)[:, 1] / WINDOW_DIMS[1] + menu_top

                # Choose an upgrade
                valid_y_locs = [y for y in potential_y_locs if min(abs(invalid_y_locs - y)) > 0.02]

                # Ignore New upgrades since logic is not implemented
                new_locs = Frame_Handler.locate(render_text("New", "CCBackBeat", 27, color=(13, 255, 13)), filter_color((13, 255, 13), menu), thresh=0.70, grayscale=False, ref="lc", normalize=False, return_all=True)
                for x, y in new_locs:
                    if len(potential_y_locs) == 0: return None, None
                    if x is None or y is None: continue
                    y_global = y / WINDOW_DIMS[1] + menu_top
                    min_idx = np.argmin(abs(potential_y_locs - y_global))
                    if abs(potential_y_locs[min_idx] - y_global) < 0.02:
                        potential_y_locs = np.delete(potential_y_locs, min_idx)

                # Prioritize discounted upgrades
                discounted_upgrades = []
                if len(valid_y_locs) > 0:
                    discounted_locs = Frame_Handler.locate(self.assets["green_tag"], menu, thresh=0.80, grayscale=False, normalize=False, return_all=True)
                    for x, y in discounted_locs:
                        if len(valid_y_locs) == 0: break
                        if x is None or y is None: continue
                        y_global = y / WINDOW_DIMS[1] + menu_top
                        min_idx = np.argmin(abs(valid_y_locs - y_global))
                        if abs(valid_y_locs[min_idx] - y_global) < 0.02:
                            discounted_upgrades.append(valid_y_locs[min_idx])
                            valid_y_locs = np.delete(valid_y_locs, min_idx)

                if len(discounted_upgrades) > 0:
                    x_upgrade, y_upgrade = menu_center, np.random.choice(discounted_upgrades)
                elif len(valid_y_locs) > 0:
                    x_upgrade, y_upgrade = menu_center, np.random.choice(valid_y_locs)
                else:
                    x_upgrade, y_upgrade = None, None

                if x_upgrade is None or y_upgrade is None:
                    # If no valid upgrades found but town hall is found, then upgrade it
                    if town_hall_loc != -1 and min(abs(town_hall_loc[1] - potential_y_locs)) < 0.02:
                        x_upgrade, y_upgrade = menu_center, town_hall_loc[1]
                    else: return None, None
                group = discounted_upgrades if len(discounted_upgrades) else valid_y_locs
                if len(group) > 0:
                    return self._choose_jev_upgrade([(menu_center, y) for y in group], (x_upgrade, y_upgrade), menu_left, menu_right, "home_base", discounted=bool(len(discounted_upgrades)))
                return x_upgrade, y_upgrade
            
            # Choose an upgrade
            x_upgrade, y_upgrade = self._scroll_locate_upgrade(
                locate_upgrade,
                menu_left,
                menu_right,
                menu_top,
                menu_bottom,
                dir="down" if configs.START_FROM_MENU_TOP else "up",
            )
            if x_upgrade is None or y_upgrade is None: return None
            Input_Handler.click(x_upgrade, y_upgrade)
            time.sleep(0.5)
            
            # Hero upgrades go directly to confirm screen now
            in_hero_hall = not get_home_builders(0, return_amount=False, raise_exception=False)
            if in_hero_hall:
                if Task_Handler.excluded("heroes"): return None
            else:
                self._click_home_builders()
                
                if not self._click_upgrade(): return None
                time.sleep(0.5)
            
            # Get upgrade name
            upgrade_name = self._get_upgrade_name([
                "buildings/home-village",
                "traps/home-village",
                "heroes",
                "guardians",
            ])
            
            # Click confirm button
            if not self._click_home_confirm(): return None
            time.sleep(0.5)
            return upgrade_name
        except (KeyboardInterrupt, SystemExit): raise
        except Exception:
            logger.exception("Upgrader.home_random_upgrade:")
            return None

    @require_exit()
    def home_specified_upgrade(self, upgrade_text):
        import time, numpy as np
        
        self._pending_jev_upgrade = None

        try:
            # Render templates
            if type(upgrade_text) == str: upgrade_text = [upgrade_text]
            if Task_Handler.excluded("heroes"):
                upgrade_text = list(set(upgrade_text) - set(Cache_Manager.get("vocab", get_vocab())["heroes"]))
            if len(upgrade_text) == 0: return None
            templates = [render_text(text, "CCBackBeat", 27) for text in upgrade_text]
            combined = list(zip(templates, upgrade_text))
            np.random.shuffle(combined)
            templates, upgrade_text = zip(*combined)
            
            # Open upgrade list menu
            self._click_home_builders()
            time.sleep(0.5)
            
            # Find suggested upgrades label
            sug_template, sug_width, sug_height = self._get_suggested_upgrade_template()
            x_sug, y_sug = Frame_Handler.locate(sug_template, thresh=0.70, grayscale=False)
            if x_sug is None or y_sug is None: return None
            frame = Frame_Handler.get_frame(grayscale=False, use_cached=True)
            menu, menu_left, menu_top, menu_right, menu_bottom = self._get_upgrade_menu(frame, (x_sug, y_sug), sug_width, return_bounds=True)
            
            # Move ongoing upgrades out of view
            if configs.START_FROM_MENU_TOP:
                Input_Handler.swipe_up(x=x_sug, y1=y_sug, y2=0.15, duration=0, hold_end_time=100, inter_points=10)
            else:
                self._scroll_to_menu_bottom(menu_left, menu_right, menu_top, menu_bottom)
            
            # Find upgrade text
            def locate_upgrade():
                frame = Frame_Handler.get_frame(grayscale=False)
                x_sug, y_sug = Frame_Handler.locate(sug_template, frame, thresh=0.70, grayscale=False)
                res = Frame_Handler.batch_locate(templates, frame, thresh=0.80, ref="lc", return_all=True, grayscale=True)
                non_discounted_upgrades = []
                discounted_upgrades = []
                for items, name in zip(res, upgrade_text):
                    for x, y in items:
                        if x is not None and y is not None and (y_sug is None or (y_sug is not None and y > y_sug)):
                            section = Frame_Handler.crop(frame, menu_left, y-0.02, menu_right, y+0.02)
                            sufficient_resources = not check_color((255, 136, 127), section, tol=10)
                            if sufficient_resources:
                                # Check that located upgrade name is left aligned
                                if abs(x - menu_left) < 0.01:
                                    non_discounted_upgrades.append((x, y, name))
                                    continue

                                # Or if it is aligned to green discount tag
                                tag_x, tag_y = Frame_Handler.locate(self.assets["green_tag"], section, thresh=0.80, grayscale=False, ref="rc", normalize=False)
                                if tag_x is not None and tag_y is not None and abs(x - (menu_left + tag_x/WINDOW_DIMS[1])) < 0.02:
                                    discounted_upgrades.append((x, y, name)) # Prioritize discounted upgrades

                group = discounted_upgrades or non_discounted_upgrades
                if group:
                    selected = self._choose_jev_upgrade(group, group[0], menu_left, menu_right, "home_base", discounted=bool(discounted_upgrades))
                    return selected[:2]
                return None, None
            
            x, y = self._scroll_locate_upgrade(
                locate_upgrade,
                menu_left,
                menu_right,
                menu_top,
                menu_bottom,
                dir="down" if configs.START_FROM_MENU_TOP else "up",
            )
            
            if x is None or y is None: return None
            Input_Handler.click(x_sug, y)
            time.sleep(0.5)
            
            # Hero upgrades go directly to confirm screen now
            in_hero_hall = not get_home_builders(0, return_amount=False, raise_exception=False)
            if in_hero_hall:
                if Task_Handler.excluded("heroes"): return None
            else:
                self._click_home_builders()
                
                if not self._click_upgrade(): return None
                time.sleep(0.5)
            
            # Get upgrade name
            upgrade_name = self._get_upgrade_name([
                "buildings/home-village",
                "traps/home-village",
                "heroes",
                "guardians",
            ])
            
            # Click confirm button
            if not self._click_home_confirm(): return None
            time.sleep(0.5)
            return upgrade_name
        except (KeyboardInterrupt, SystemExit): raise
        except Exception:
            logger.exception("Upgrader.home_specified_upgrade:")
            return None
    
    @require_exit()
    def home_upgrade(self):
        if not Task_Handler.excluded("home_base_priority"):
            for priority_level in configs.HOME_BASE_UPGRADE_PRIORITY:
                upgrade_name = self.home_specified_upgrade(priority_level)
                if upgrade_name is not None: return upgrade_name
        return self.home_random_upgrade()
    
    @require_exit()
    def assign_builder_apprentice(self):
        import time
        
        try:
            # Open upgrade list menu
            self._click_home_builders()
            time.sleep(0.5)
            
            # Find assistant available label
            xys = Frame_Handler.locate(self.assets["assistant_available"], thresh=0.8, return_all=True)
            xys = sorted(xys, key=lambda pair: pair[1])
            if len(xys) == 0: return
            x, y = xys[0]
            if x is None or y is None: return

            Input_Handler.click(x, y)
            time.sleep(0.5)
            
            # Find assign assistant label
            xys = Frame_Handler.locate(self.assets["assign_assistant"], thresh=0.9, grayscale=False, return_all=True)
            if len(xys) == 0: return
            
            x, y = sorted(xys, key=lambda pair: pair[1])[0]
            if x is None or y is None: return
            
            Input_Handler.click(x, y)
            time.sleep(0.5)
            
            # Find confirm button
            x, y = Frame_Handler.locate(self.assets["confirm_assistant"], grayscale=False, thresh=0.9)
            if x is None or y is None: return
            
            Input_Handler.click(x, y)
            time.sleep(0.5)
        except (KeyboardInterrupt, SystemExit): raise
        except Exception:
            logger.exception("Upgrader.assign_builder_apprentice:")
    
    @require_exit()
    def home_lab_random_upgrade(self):
        import time, numpy as np
        
        self._pending_jev_upgrade = None

        try:
            # Open lab upgrade list menu
            self._click_home_lab()
            time.sleep(0.5)
            
            # Locate menu boundaries
            sug_template, sug_width, sug_height = self._get_suggested_upgrade_template()
            x_sug, y_sug = Frame_Handler.locate(sug_template, thresh=0.70, grayscale=False)
            if x_sug is None or y_sug is None: return None
            frame = Frame_Handler.get_frame(grayscale=False, use_cached=True)
            menu, menu_left, menu_top, menu_right, menu_bottom = self._get_upgrade_menu(frame, (x_sug, y_sug), sug_width, return_bounds=True)
            menu_center = (menu_left + menu_right) / 2
            if configs.START_FROM_MENU_TOP:
                Input_Handler.swipe_up(x=x_sug, y1=y_sug, y2=0.15, duration=0, hold_end_time=100, inter_points=10)
            else:
                self._scroll_to_menu_bottom(menu_left, menu_right, menu_top, menu_bottom)
            
            def locate_upgrade():
                frame = Frame_Handler.get_frame(grayscale=False)
                menu = Frame_Handler.crop(frame, menu_left, menu_top, menu_right, menu_bottom)
                x_sug, y_sug = Frame_Handler.locate(sug_template, frame, thresh=0.70, grayscale=False)

                # Find a valid upgrade
                potential_y_locs = self._get_potential_upgrade_locs(menu)
                if len(potential_y_locs) == 0: return None, None
                potential_y_locs = potential_y_locs / WINDOW_DIMS[1] + menu_top
                if y_sug is not None: potential_y_locs = potential_y_locs[potential_y_locs > y_sug]

                # Determine discounted upgrades
                discounted_locs = Frame_Handler.locate(self.assets["green_tag"], menu, thresh=0.80, grayscale=False, return_all=True, normalize=False)
                discounted_upgrades = []
                for x, y in discounted_locs:
                    if len(potential_y_locs) == 0: break
                    if x is None or y is None: continue
                    y_global = y / WINDOW_DIMS[1] + menu_top
                    min_idx = np.argmin(abs(potential_y_locs - y_global))
                    if abs(potential_y_locs[min_idx] - y_global) < 0.02:
                        discounted_upgrades.append(potential_y_locs[min_idx])
                        potential_y_locs = np.delete(potential_y_locs, min_idx)

                # Choose an upgrade
                group = discounted_upgrades if len(discounted_upgrades) else potential_y_locs
                if len(group) == 0: return None, None
                legacy = (menu_center, np.random.choice(group))
                return self._choose_jev_upgrade([(menu_center, y) for y in group], legacy, menu_left, menu_right, "home_lab", discounted=bool(len(discounted_upgrades)))
            
            x_upgrade, y_upgrade = self._scroll_locate_upgrade(
                locate_upgrade,
                menu_left,
                menu_right,
                menu_top,
                menu_bottom,
                dir="down" if configs.START_FROM_MENU_TOP else "up",
            )
            if x_upgrade is None or y_upgrade is None: return None
            Input_Handler.click(x_upgrade, y_upgrade)
            time.sleep(0.5)
            
            # Get upgrade name
            upgrade_name = self._get_upgrade_name([
                "troops",
                "spells",
            ])

            # Click confirm button
            if not self._click_home_confirm(): return None
            time.sleep(0.5)
            return upgrade_name
        except (KeyboardInterrupt, SystemExit): raise
        except Exception:
            logger.exception("Upgrader.home_lab_random_upgrade:")
            return None
    
    @require_exit()
    def home_lab_specified_upgrade(self, upgrade_text):
        import time, numpy as np
        
        self._pending_jev_upgrade = None

        try:
            # Render templates
            if type(upgrade_text) == str: upgrade_text = [upgrade_text]
            if len(upgrade_text) == 0: return None
            templates = [render_text(text, "CCBackBeat", 27) for text in upgrade_text]
            combined = list(zip(templates, upgrade_text))
            np.random.shuffle(combined)
            templates, upgrade_text = zip(*combined)
            
            # Open lab upgrade list menu
            self._click_home_lab()
            time.sleep(0.5)
            
            # Find suggested upgrades label
            sug_template, sug_width, sug_height = self._get_suggested_upgrade_template()
            x_sug, y_sug = Frame_Handler.locate(sug_template, thresh=0.70, grayscale=False)
            if x_sug is None or y_sug is None: return None
            frame = Frame_Handler.get_frame(grayscale=False, use_cached=True)
            menu, menu_left, menu_top, menu_right, menu_bottom = self._get_upgrade_menu(frame, (x_sug, y_sug), sug_width, return_bounds=True)
            
            # Move ongoing upgrades out of view
            if configs.START_FROM_MENU_TOP:
                Input_Handler.swipe_up(x=x_sug, y1=y_sug, y2=0.15, duration=0, hold_end_time=100, inter_points=10)
            else:
                self._scroll_to_menu_bottom(menu_left, menu_right, menu_top, menu_bottom)
            
            # Find upgrade text
            def locate_upgrade():
                frame = Frame_Handler.get_frame(grayscale=False)
                x_sug, y_sug = Frame_Handler.locate(sug_template, frame, thresh=0.70, grayscale=False)
                xys = Frame_Handler.batch_locate(templates, frame, thresh=0.80, ref="lc", grayscale=True)
                non_discounted_upgrades = []
                discounted_upgrades = []
                for (x, y), name in zip(xys, upgrade_text):
                    if x is not None and y is not None and (y_sug is None or (y_sug is not None and y > y_sug)):
                        section = Frame_Handler.crop(frame, menu_left, y-0.02, menu_right, y+0.02)
                        sufficient_resources = not check_color((255, 136, 127), section, tol=10)
                        if sufficient_resources:
                            # Check that located upgrade name is left aligned
                            if abs(x - menu_left) < 0.01:
                                non_discounted_upgrades.append((x, y, name))
                                continue

                            # Or if it is aligned to green discount tag
                            tag_x, tag_y = Frame_Handler.locate(self.assets["green_tag"], section, thresh=0.80, grayscale=False, ref="rc", normalize=False)
                            if tag_x is not None and tag_y is not None and abs(x - (menu_left + tag_x/WINDOW_DIMS[1])) < 0.02:
                                discounted_upgrades.append((x, y, name)) # Prioritize discounted upgrades

                            # Or if it is left aligned to "New" label
                            new_x, new_y = Frame_Handler.locate(render_text("New", "CCBackBeat", 27, color=(13, 255, 13)), filter_color((13, 255, 13), section), thresh=0.70, grayscale=False, ref="rc", normalize=False)
                            if new_x is not None and new_y is not None and abs(x - (menu_left + new_x/WINDOW_DIMS[1])) < 0.02:
                                non_discounted_upgrades.append((x, y, name))
                                continue
                
                group = discounted_upgrades or non_discounted_upgrades
                if group:
                    selected = self._choose_jev_upgrade(group, group[0], menu_left, menu_right, "home_lab", discounted=bool(discounted_upgrades))
                    return selected[:2]
                return None, None
            
            x, y = self._scroll_locate_upgrade(
                locate_upgrade,
                menu_left,
                menu_right,
                menu_top,
                menu_bottom,
                dir="down" if configs.START_FROM_MENU_TOP else "up",
            )
            
            if x is None or y is None: return None
            Input_Handler.click(x, y)
            time.sleep(0.5)
            
            # Get upgrade name
            upgrade_name = self._get_upgrade_name([
                "troops",
                "spells",
            ])
            
            # Click confirm button
            if not self._click_home_confirm(): return None
            time.sleep(0.5)
            return upgrade_name
        except (KeyboardInterrupt, SystemExit): raise
        except Exception:
            logger.exception("Upgrader.home_lab_specified_upgrade:")
            return None
    
    @require_exit()
    def home_lab_upgrade(self):
        if not Task_Handler.excluded("home_lab_priority"):
            for priority_level in configs.HOME_LAB_UPGRADE_PRIORITY:
                upgrade_name = self.home_lab_specified_upgrade(priority_level)
                if upgrade_name is not None: return upgrade_name
        return self.home_lab_random_upgrade()

    @require_exit()
    def assign_lab_assistant(self):
        import time
        
        try:
            # Open upgrade list menu
            self._click_home_lab()
            time.sleep(0.5)
            
            # Find assistant available label
            xys = Frame_Handler.locate(self.assets["assistant_available"], thresh=0.8, return_all=True)
            xys = sorted(xys, key=lambda pair: pair[1])
            if len(xys) == 0: return
            x, y = xys[0]
            if x is None or y is None: return
            
            Input_Handler.click(x, y)
            time.sleep(0.5)
            
            # Find assign assistant label
            xys = Frame_Handler.locate(self.assets["assign_assistant"], thresh=0.9, grayscale=False, return_all=True)
            if len(xys) == 0: return
            
            x, y = sorted(xys, key=lambda pair: pair[1])[0]
            if x is None or y is None: return
            
            Input_Handler.click(x, y)
            time.sleep(0.5)
            
            # Find confirm button
            x, y = Frame_Handler.locate(self.assets["confirm_assistant"], grayscale=False, thresh=0.9)
            if x is None or y is None: return
            
            Input_Handler.click(x, y)
            time.sleep(0.5)
        except (KeyboardInterrupt, SystemExit): raise
        except Exception:
            logger.exception("Upgrader.assign_lab_assistant:")
    
    @require_exit()
    def builder_random_upgrade(self):
        import time, re, numpy as np
        
        self._pending_jev_upgrade = None

        try:
            # Open upgrade list menu
            self._click_builder_builders()
            time.sleep(0.5)
            
            # Locate menu boundaries
            sug_template, sug_width, sug_height = self._get_suggested_upgrade_template()
            x_sug, y_sug = Frame_Handler.locate(sug_template, thresh=0.70, grayscale=False)
            if x_sug is None or y_sug is None: return None
            frame = Frame_Handler.get_frame(grayscale=False, use_cached=True)
            menu, menu_left, menu_top, menu_right, menu_bottom = self._get_upgrade_menu(frame, (x_sug, y_sug), sug_width, return_bounds=True)
            menu_center = (menu_left + menu_right) / 2
            if configs.START_FROM_MENU_TOP:
                Input_Handler.swipe_up(x=x_sug, y1=y_sug, y2=0.15, duration=0, hold_end_time=100, inter_points=10)
            else:
                self._scroll_to_menu_bottom(menu_left, menu_right, menu_top, menu_bottom)
            
            def locate_upgrade():
                frame = Frame_Handler.get_frame(grayscale=False)
                menu = Frame_Handler.crop(frame, menu_left, menu_top, menu_right, menu_bottom)
                x_sug, y_sug = Frame_Handler.locate(sug_template, frame, thresh=0.70, grayscale=False)

                # Find a valid upgrade
                potential_y_locs = self._get_potential_upgrade_locs(menu)
                if len(potential_y_locs) == 0: return None, None
                potential_y_locs = potential_y_locs / WINDOW_DIMS[1] + menu_top
                if y_sug is not None: potential_y_locs = potential_y_locs[potential_y_locs > y_sug]
                
                # Ignore New upgrades since logic is not implemented
                new_locs = Frame_Handler.locate(render_text("New", "CCBackBeat", 27, color=(13, 255, 13)), filter_color((13, 255, 13), menu), thresh=0.70, grayscale=False, ref="lc", normalize=False, return_all=True)
                for x, y in new_locs:
                    if len(potential_y_locs) == 0: return None, None
                    if x is None or y is None: continue
                    y_global = y / WINDOW_DIMS[1] + menu_top
                    min_idx = np.argmin(abs(potential_y_locs - y_global))
                    if abs(potential_y_locs[min_idx] - y_global) < 0.02:
                        potential_y_locs = np.delete(potential_y_locs, min_idx)
                
                # Determine discounted upgrades
                discounted_locs = Frame_Handler.locate(self.assets["green_tag"], menu, thresh=0.80, grayscale=False, return_all=True, normalize=False)
                discounted_upgrades = []
                for x, y in discounted_locs:
                    if len(potential_y_locs) == 0: break
                    if x is None or y is None: continue
                    y_global = y / WINDOW_DIMS[1] + menu_top
                    min_idx = np.argmin(abs(potential_y_locs - y_global))
                    if abs(potential_y_locs[min_idx] - y_global) < 0.02:
                        discounted_upgrades.append(potential_y_locs[min_idx])
                        potential_y_locs = np.delete(potential_y_locs, min_idx)

                # Choose an upgrade
                group = discounted_upgrades if len(discounted_upgrades) else potential_y_locs
                if len(group) == 0: return None, None
                legacy = (menu_center, np.random.choice(group))
                return self._choose_jev_upgrade([(menu_center, y) for y in group], legacy, menu_left, menu_right, "builder_base", discounted=bool(len(discounted_upgrades)))
            
            x_upgrade, y_upgrade = self._scroll_locate_upgrade(
                locate_upgrade,
                menu_left,
                menu_right,
                menu_top,
                menu_bottom,
                dir="down" if configs.START_FROM_MENU_TOP else "up",
            )
            if x_upgrade is None or y_upgrade is None: return None
            
            # Get upgrade name
            section = Frame_Handler.high_contrast(Frame_Handler.get_frame_section(menu_left, y_upgrade - 0.035, menu_center, y_upgrade + 0.025))
            upgrade_name = spell_check(re.sub(r"\s*x\d+$", "", OCR_Handler.get_text(section)[0].lower()), ["buildings/builder-base", "traps/builder-base"], phrase_level=True)
            
            # Select upgrade
            Input_Handler.click(x_upgrade, y_upgrade)
            
            # Exit upgrade menu
            self._click_builder_builders()
            
            # Click upgrade button
            if not self._click_upgrade(): return None
            
            # Click confirm button
            if not self._click_builder_confirm(): return None
            time.sleep(0.5)
            return upgrade_name
        except (KeyboardInterrupt, SystemExit): raise
        except Exception:
            logger.exception("Upgrader.builder_random_upgrade:")
            return None
    
    @require_exit()
    def builder_specified_upgrade(self, upgrade_text):
        import time, numpy as np
        
        self._pending_jev_upgrade = None

        try:
            # Render templates
            if type(upgrade_text) == str: upgrade_text = [upgrade_text]
            if len(upgrade_text) == 0: return None
            templates = [render_text(text, "CCBackBeat", 27) for text in upgrade_text]
            combined = list(zip(templates, upgrade_text))
            np.random.shuffle(combined)
            templates, upgrade_text = zip(*combined)
            
            # Open upgrade list menu
            self._click_builder_builders()
            time.sleep(0.5)
            
            # Find suggested upgrades label
            sug_template, sug_width, sug_height = self._get_suggested_upgrade_template()
            x_sug, y_sug = Frame_Handler.locate(sug_template, thresh=0.70, grayscale=False)
            if x_sug is None or y_sug is None: return None
            frame = Frame_Handler.get_frame(grayscale=False, use_cached=True)
            menu, menu_left, menu_top, menu_right, menu_bottom = self._get_upgrade_menu(frame, (x_sug, y_sug), sug_width, return_bounds=True)

            # Move ongoing upgrades out of view
            if configs.START_FROM_MENU_TOP:
                Input_Handler.swipe_up(x=x_sug, y1=y_sug, y2=0.15, duration=0, hold_end_time=100, inter_points=10)
            else:
                self._scroll_to_menu_bottom(menu_left, menu_right, menu_top, menu_bottom)
            
            # Find upgrade text
            def locate_upgrade():
                frame = Frame_Handler.get_frame(grayscale=False)
                x_sug, y_sug = Frame_Handler.locate(sug_template, frame, thresh=0.70, grayscale=False)
                xys = Frame_Handler.batch_locate(templates, frame, thresh=0.80, ref="lc", grayscale=True)
                non_discounted_upgrades = []
                discounted_upgrades = []
                for (x, y), name in zip(xys, upgrade_text):
                    if x is not None and y is not None and (y_sug is None or (y_sug is not None and y > y_sug)):
                        section = Frame_Handler.crop(frame, menu_left, y-0.02, menu_right, y+0.02)
                        sufficient_resources = not check_color((255, 136, 127), section, tol=10)
                        if sufficient_resources:
                            # Check that located upgrade name is left aligned
                            if abs(x - menu_left) < 0.01:
                                non_discounted_upgrades.append((x, y, name))
                                continue
                            
                            # Or if it is aligned to green discount tag
                            tag_x, tag_y = Frame_Handler.locate(self.assets["green_tag"], section, thresh=0.80, grayscale=False, ref="rc", normalize=False)
                            if tag_x is not None and tag_y is not None and abs(x - (menu_left + tag_x/WINDOW_DIMS[1])) < 0.02:
                                discounted_upgrades.append((x, y, name)) # Prioritize discounted upgrades

                group = discounted_upgrades or non_discounted_upgrades
                if group:
                    return self._choose_jev_upgrade(group, group[0], menu_left, menu_right, "builder_base", discounted=bool(discounted_upgrades))
                return None, None, None
            
            x, y, upgrade_name = self._scroll_locate_upgrade(
                locate_upgrade,
                menu_left,
                menu_right,
                menu_top,
                menu_bottom,
                dir="down" if configs.START_FROM_MENU_TOP else "up"
            )
            
            if x is None or y is None: return None
            Input_Handler.click(x, y)
            time.sleep(0.5)
            
            self._click_builder_builders()
            
            # Click upgrade
            if not self._click_upgrade(): return None
            
            # Click confirm button
            if not self._click_builder_confirm(): return None
            time.sleep(0.5)
            return upgrade_name
        except (KeyboardInterrupt, SystemExit): raise
        except Exception:
            logger.exception("Upgrader.builder_specified_upgrade:")
            return None
    
    @require_exit()
    def builder_upgrade(self):
        if not Task_Handler.excluded("builder_base_priority"):
            for priority_level in configs.BUILDER_BASE_UPGRADE_PRIORITY:
                upgrade_name = self.builder_specified_upgrade(priority_level)
                if upgrade_name is not None: return upgrade_name
        return self.builder_random_upgrade()
    
    @require_exit()
    def builder_lab_random_upgrade(self):
        import time, re, numpy as np
        
        self._pending_jev_upgrade = None

        try:
            # Open lab upgrade list menu
            self._click_builder_lab()
            time.sleep(0.5)
            
            # Locate menu boundaries
            sug_template, sug_width, sug_height = self._get_suggested_upgrade_template()
            x_sug, y_sug = Frame_Handler.locate(sug_template, thresh=0.70, grayscale=False)
            if x_sug is None or y_sug is None: return None
            frame = Frame_Handler.get_frame(grayscale=False, use_cached=True)
            menu, menu_left, menu_top, menu_right, menu_bottom = self._get_upgrade_menu(frame, (x_sug, y_sug), sug_width, return_bounds=True)
            menu_center = (menu_left + menu_right) / 2
            if configs.START_FROM_MENU_TOP:
                Input_Handler.swipe_up(x=x_sug, y1=y_sug, y2=0.15, duration=0, hold_end_time=100, inter_points=10)
            else:
                self._scroll_to_menu_bottom(menu_left, menu_right, menu_top, menu_bottom)
            
            def locate_upgrade():
                frame = Frame_Handler.get_frame(grayscale=False)
                menu = Frame_Handler.crop(frame, menu_left, menu_top, menu_right, menu_bottom)
                x_sug, y_sug = Frame_Handler.locate(sug_template, frame, thresh=0.70, grayscale=False)
                
                # Find a valid upgrade
                potential_y_locs = self._get_potential_upgrade_locs(menu)
                if len(potential_y_locs) == 0: return None, None
                potential_y_locs = potential_y_locs / WINDOW_DIMS[1] + menu_top
                if y_sug is not None: potential_y_locs = potential_y_locs[potential_y_locs > y_sug]
                
                # Determine discounted upgrades
                discounted_locs = Frame_Handler.locate(self.assets["green_tag"], menu, thresh=0.80, grayscale=False, return_all=True, normalize=False)
                discounted_upgrades = []
                for x, y in discounted_locs:
                    if len(potential_y_locs) == 0: break
                    if x is None or y is None: continue
                    y_global = y / WINDOW_DIMS[1] + menu_top
                    min_idx = np.argmin(abs(potential_y_locs - y_global))
                    if abs(potential_y_locs[min_idx] - y_global) < 0.02:
                        discounted_upgrades.append(potential_y_locs[min_idx])
                        potential_y_locs = np.delete(potential_y_locs, min_idx)

                # Choose an upgrade
                group = discounted_upgrades if len(discounted_upgrades) else potential_y_locs
                if len(group) == 0: return None, None
                legacy = (menu_center, np.random.choice(group))
                return self._choose_jev_upgrade([(menu_center, y) for y in group], legacy, menu_left, menu_right, "builder_lab", discounted=bool(len(discounted_upgrades)))
            
            x_upgrade, y_upgrade = self._scroll_locate_upgrade(
                locate_upgrade,
                menu_left,
                menu_right,
                menu_top,
                menu_bottom,
                dir="down" if configs.START_FROM_MENU_TOP else "up",
            )
            if x_upgrade is None or y_upgrade is None: return None
            
            # Get upgrade name
            section = Frame_Handler.high_contrast(Frame_Handler.get_frame_section(menu_left, y_upgrade - 0.035, menu_center, y_upgrade + 0.025))
            upgrade_name = spell_check(re.sub(r"\s*x\d+$", "", OCR_Handler.get_text(section)[0].lower()), "troops", phrase_level=True)
            
            # Select upgrade
            Input_Handler.click(x_upgrade, y_upgrade)
            
            # Click confirm button
            if not self._click_builder_confirm(): return None
            time.sleep(0.5)
            return upgrade_name
        except (KeyboardInterrupt, SystemExit): raise
        except Exception:
            logger.exception("Upgrader.builder_lab_random_upgrade:")
            return None
    
    @require_exit()
    def builder_lab_specified_upgrade(self, upgrade_text):
        import time, numpy as np
        
        self._pending_jev_upgrade = None

        try:
            # Render templates
            if type(upgrade_text) == str: upgrade_text = [upgrade_text]
            if len(upgrade_text) == 0: return None
            templates = [render_text(text, "CCBackBeat", 27) for text in upgrade_text]
            combined = list(zip(templates, upgrade_text))
            np.random.shuffle(combined)
            templates, upgrade_text = zip(*combined)
            
            # Open lab upgrade list menu
            self._click_builder_lab()
            time.sleep(0.5)
            
            # Find suggested upgrades label
            sug_template, sug_width, sug_height = self._get_suggested_upgrade_template()
            x_sug, y_sug = Frame_Handler.locate(sug_template, thresh=0.70, grayscale=False)
            if x_sug is None or y_sug is None: return None
            frame = Frame_Handler.get_frame(grayscale=False, use_cached=True)
            menu, menu_left, menu_top, menu_right, menu_bottom = self._get_upgrade_menu(frame, (x_sug, y_sug), sug_width, return_bounds=True)

            # Move ongoing upgrades out of view
            if configs.START_FROM_MENU_TOP:
                Input_Handler.swipe_up(x=x_sug, y1=y_sug, y2=0.15, duration=0, hold_end_time=100, inter_points=10)
            else:
                self._scroll_to_menu_bottom(menu_left, menu_right, menu_top, menu_bottom)
            
            # Find upgrade text
            def locate_upgrade():
                frame = Frame_Handler.get_frame(grayscale=False)
                x_sug, y_sug = Frame_Handler.locate(sug_template, frame, thresh=0.70, grayscale=False)
                xys = Frame_Handler.batch_locate(templates, frame, thresh=0.80, ref="lc", grayscale=True)
                non_discounted_upgrades = []
                discounted_upgrades = []
                for (x, y), name in zip(xys, upgrade_text):
                    if x is not None and y is not None and (y_sug is None or (y_sug is not None and y > y_sug)):
                        section = Frame_Handler.crop(frame, menu_left, y-0.02, menu_right, y+0.02)
                        sufficient_resources = not check_color((255, 136, 127), section, tol=10)
                        if sufficient_resources:
                            # Check that located upgrade name is left aligned
                            if abs(x - menu_left) < 0.01:
                                non_discounted_upgrades.append((x, y, name))
                                continue
                            
                            # Or if it is aligned to green discount tag
                            tag_x, tag_y = Frame_Handler.locate(self.assets["green_tag"], section, thresh=0.80, grayscale=False, ref="rc", normalize=False)
                            if tag_x is not None and tag_y is not None and abs(x - (menu_left + tag_x/WINDOW_DIMS[1])) < 0.02:
                                discounted_upgrades.append((x, y, name)) # Prioritize discounted upgrades

                            # Or if it is left aligned to "New" label
                            new_x, new_y = Frame_Handler.locate(render_text("New", "CCBackBeat", 27, color=(13, 255, 13)), filter_color((13, 255, 13), section), thresh=0.70, grayscale=False, ref="rc", normalize=False)
                            if new_x is not None and new_y is not None and abs(x - (menu_left + new_x/WINDOW_DIMS[1])) < 0.02:
                                non_discounted_upgrades.append((x, y, name))
                                continue

                group = discounted_upgrades or non_discounted_upgrades
                if group:
                    return self._choose_jev_upgrade(group, group[0], menu_left, menu_right, "builder_lab", discounted=bool(discounted_upgrades))
                return None, None, None
            
            x, y, upgrade_name = self._scroll_locate_upgrade(
                locate_upgrade,
                menu_left,
                menu_right,
                menu_top,
                menu_bottom,
                dir="down" if configs.START_FROM_MENU_TOP else "up",
            )
            
            if x is None or y is None: return None
            Input_Handler.click(x, y)
            
            # Find confirm button
            if not self._click_builder_confirm(): return None
            time.sleep(0.5)
            return upgrade_name
        except (KeyboardInterrupt, SystemExit): raise
        except Exception:
            logger.exception("Upgrader.builder_lab_specified_upgrade:")
            return None
    
    @require_exit()
    def builder_lab_upgrade(self):
        if not Task_Handler.excluded("builder_lab_priority"):
            for priority_level in configs.BUILDER_LAB_UPGRADE_PRIORITY:
                upgrade_name = self.builder_lab_specified_upgrade(priority_level)
                if upgrade_name is not None: return upgrade_name
        return self.builder_lab_random_upgrade()
    
    # ============================================================
    # 📡 Upgrade Monitoring
    # ============================================================
    
    def run_home_base(self, exclude_base=False, exclude_lab=False):
        import time
        
        Input_Handler.zoom(dir="out")
        Input_Handler.swipe_down()
        
        # Building upgrades
        upgrades_started = []
        if not exclude_base:
            counter = 0
            while counter < MAX_UPGRADES_PER_CHECK:
                counter += 1
                try:
                    initial_builders = get_home_builders(1)
                    if initial_builders <= max(0, OPEN_HOME_BUILDERS): break
                    self._jev_availability = {'builders': initial_builders, 'lab_available': None}
                    upgrade_started = time.monotonic()
                    upgraded = self.home_upgrade()
                    time.sleep(0.5)
                    final_builders = get_home_builders(1)
                    self.decisions.record('upgrade_outcome', village='home_base', name=upgraded,
                        success=(final_builders < initial_builders) if upgraded != 'wall' else None,
                        duration_seconds=time.monotonic()-upgrade_started)
                    if upgraded is not None:
                        upgraded = upgraded.lower()
                        if final_builders < initial_builders: upgrades_started.append(upgraded)
                        elif final_builders == initial_builders and upgraded != "wall": break
                    else: break
                except (KeyboardInterrupt, SystemExit): raise
                except: pass
        if not Task_Handler.excluded("builder_apprentice"):
            self.assign_builder_apprentice()
        
        # Lab upgrades
        lab_upgrades_started = []
        try:
            if not exclude_lab and self.home_lab_available(1):
                self._jev_availability = {'builders': None, 'lab_available': True}
                upgrade_started = time.monotonic()
                upgraded = self.home_lab_upgrade()
                time.sleep(0.5)
                final_lab_avail = self.home_lab_available(1)
                self.decisions.record('upgrade_outcome', village='home_lab', name=upgraded,
                    success=upgraded is not None and not final_lab_avail, duration_seconds=time.monotonic()-upgrade_started)
                if upgraded is not None and not final_lab_avail: lab_upgrades_started.append(upgraded.lower())
        except (KeyboardInterrupt, SystemExit): raise
        except: pass
        if not Task_Handler.excluded("lab_assistant"):
            self.assign_lab_assistant()
        
        for upgrade in upgrades_started + lab_upgrades_started:
            send_notification(f"Started upgrading {upgrade}")
    
    def run_builder_base(self, exclude_base=False, exclude_lab=False):
        import time
        
        Input_Handler.zoom(dir="out")
        Input_Handler.swipe_down()
        
        # Building upgrades
        upgrades_started = []
        if not exclude_base:
            counter = 0
            while counter < MAX_UPGRADES_PER_CHECK:
                counter += 1
                try:
                    initial_builders = get_builder_builders(1)
                    if initial_builders <= max(0, OPEN_BUILDER_BUILDERS): break
                    self._jev_availability = {'builders': initial_builders, 'lab_available': None}
                    upgrade_started = time.monotonic()
                    upgraded = self.builder_upgrade()
                    time.sleep(0.5)
                    final_builders = get_builder_builders(1)
                    self.decisions.record('upgrade_outcome', village='builder_base', name=upgraded,
                        success=(final_builders < initial_builders) if upgraded != 'wall' else None,
                        duration_seconds=time.monotonic()-upgrade_started)
                    if upgraded is not None:
                        upgraded = upgraded.lower()
                        if final_builders < initial_builders: upgrades_started.append(upgraded)
                        elif final_builders == initial_builders and upgraded != "wall": break
                    else: break
                except (KeyboardInterrupt, SystemExit): raise
                except: pass
        
        # Lab upgrades
        lab_upgrades_started = []
        try:
            if not exclude_lab and self.builder_lab_available(1):
                self._jev_availability = {'builders': None, 'lab_available': True}
                upgrade_started = time.monotonic()
                upgraded = self.builder_lab_upgrade()
                time.sleep(0.5)
                final_lab_avail = self.builder_lab_available(1)
                self.decisions.record('upgrade_outcome', village='builder_lab', name=upgraded,
                    success=upgraded is not None and not final_lab_avail, duration_seconds=time.monotonic()-upgrade_started)
                if upgraded is not None and not final_lab_avail: lab_upgrades_started.append(upgraded.lower())
        except (KeyboardInterrupt, SystemExit): raise
        except: pass
        
        for upgrade in upgrades_started + lab_upgrades_started:
            send_notification(f"Started upgrading {upgrade}")
