/* HR 2027 — searchable employee picker */
(function() {
  function bindQtSearch(root) {
    var boxes = (root || document).querySelectorAll('.qt-search');
    boxes.forEach(function(box) {
      if (box.dataset.bound) return;
      box.dataset.bound = '1';
      var input = box.querySelector('.qt-search-input');
      var hidden = box.querySelector('.qt-search-hidden');
      var list = box.querySelector('.qt-search-list');
      var clear = box.querySelector('.qt-search-clear');
      var empty = box.querySelector('.qt-search-empty');
      var items = Array.prototype.slice.call(box.querySelectorAll('.qt-search-item'));

      function filter() {
        var q = (input.value || '').trim().toLowerCase();
        var shown = 0;
        items.forEach(function(it) {
          var m = it.dataset.query.indexOf(q) !== -1;
          it.style.display = m ? '' : 'none';
          if (m) shown++;
        });
        if (empty) empty.style.display = shown ? 'none' : '';
      }

      function select(it) {
        hidden.value = it.dataset.id;
        input.value = it.querySelector('.qt-search-name').textContent;
        items.forEach(function(x) { x.classList.remove('is-selected'); });
        it.classList.add('is-selected');
        list.classList.remove('is-open');
        input.classList.add('is-filled');
      }

      input.addEventListener('focus', function() {
        list.classList.add('is-open');
        if (input.value) filter();
      });
      input.addEventListener('input', filter);
      document.addEventListener('click', function(e) {
        if (!box.contains(e.target)) list.classList.remove('is-open');
      });
      items.forEach(function(it) {
        it.addEventListener('click', function() { select(it); });
      });
      if (clear) {
        clear.addEventListener('click', function() {
          hidden.value = '';
          input.value = '';
          input.classList.remove('is-filled');
          items.forEach(function(x) { x.classList.remove('is-selected'); });
          filter();
          input.focus();
        });
      }

      input.addEventListener('keydown', function(e) {
        if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
          e.preventDefault();
          list.classList.add('is-open');
          var vis = items.filter(function(x) { return x.style.display !== 'none'; });
          if (!vis.length) return;
          var idx = vis.indexOf(box.querySelector('.is-selected'));
          idx = e.key === 'ArrowDown' ? (idx + 1) % vis.length : (idx - 1 + vis.length) % vis.length;
          vis.forEach(function(x) { x.classList.remove('is-selected'); });
          vis[idx].classList.add('is-selected');
          vis[idx].scrollIntoView({ block: 'nearest' });
        } else if (e.key === 'Enter') {
          var sel = box.querySelector('.qt-search-item.is-selected');
          if (sel && list.classList.contains('is-open')) {
            e.preventDefault();
            select(sel);
          }
        } else if (e.key === 'Escape') {
          list.classList.remove('is-open');
        }
      });

      var form = box.closest('form');
      if (form) {
        form.addEventListener('submit', function(e) {
          if (box.dataset.required && !hidden.value) {
            e.preventDefault();
            e.stopPropagation();
            input.classList.add('is-err');
            input.placeholder = 'Select an employee!';
            list.classList.add('is-open');
            setTimeout(function() { input.classList.remove('is-err'); }, 1500);
          }
        });
      }
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', function() { bindQtSearch(); });
  } else {
    bindQtSearch();
  }
})();
