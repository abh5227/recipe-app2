Put recipe photos in this folder.

Each recipe looks for a file named after its id (the slug), as set in seed.py:

    images/mussakhan.jpg
    images/aloo-gobhi.jpg
    images/gai-yang.jpg
    images/no-knead-bread.jpg
    images/bulgogi-bowls.jpg

Your recipe exports already contain the dish photos — look inside the
"Images/" subfolder of each exported recipe, copy the photo here, and rename
it to match the list above. Refresh the page and it appears.

Until a file is here, the recipe shows a tidy placeholder with its name, so
nothing looks broken.

Tips:
- .jpg, .png, and .webp all work. To use a different name or type, change the
  "image" value for that recipe in seed.py and rebuild (python build_db.py).
- Phone photos are often 5-10 MB, which loads slowly. Resizing the long edge
  to ~1600px keeps them sharp while loading fast.
