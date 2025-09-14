# Reason Codes (Images)

| Reason              | Short definition                                                                 |
|---------------------|-----------------------------------------------------------------------------------|
| no_images           | images_count == 0                                                                 |
| partial             | unzip failed OR 0 < images_count < PhotoCount                                     |
| late_active_change  | transitioned Active→Sold/Leased AND we missed an Active-time change (catch-up)    |
