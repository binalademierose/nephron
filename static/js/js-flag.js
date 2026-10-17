/* Runs in <head>, before the first paint: lets motion.css know scripting is available, so it only hides a "before" state
   when something will actually reveal it. A tiny file on purpose - see static/css/motion.css. */
document.documentElement.className += " js";
