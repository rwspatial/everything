# Local Moran's I clusters and outliers (spdep). Run by the worker as: Rscript --vanilla run.R
suppressPackageStartupMessages({ library(sf); library(spdep) })
source(file.path(Sys.getenv("WORKER_HOME"), "rlib", "ctx.R"))

ctx <- ctx_open()
inp <- ctx$inputs
field <- inp$field
label <- if (is.null(inp$label) || identical(inp$label, "")) NULL else inp$label
alpha <- if (is.null(inp$alpha)) 0.05 else as.numeric(inp$alpha)
set.seed(12345)

ctx_progress(ctx, 0.05, "reading")
x <- ctx_read_collection(ctx, inp$collection, unique(c(field, label)))
total <- nrow(x)
x <- x[!is.na(x[[field]]), ]
y <- as.numeric(x[[field]])

ctx_progress(ctx, 0.2, "building neighbours")
nb <- poly2nb(x, queen = TRUE)
no_neighbours <- sum(card(nb) == 0)
lw <- nb2listw(nb, style = "W", zero.policy = TRUE)

ctx_progress(ctx, 0.4, "computing local Moran's I")
lm <- localmoran_perm(y, lw, nsim = 999, zero.policy = TRUE, alternative = "two.sided")
p <- lm[, ncol(lm)]                                   # permutation p-value (last column)
quad <- as.character(attr(lm, "quadr")$mean)          # High-High, Low-Low, High-Low, Low-High
cluster <- ifelse(card(nb) == 0, "No neighbours", ifelse(p < alpha, quad, "Not significant"))
global <- moran.test(y, lw, zero.policy = TRUE, randomisation = TRUE)

out <- data.frame(id = as.integer(x$id),
                  label = if (is.null(label)) as.character(x$id) else as.character(x[[label]]),
                  value = y, local_i = round(lm[, 1], 4), p_value = round(p, 4), cluster = cluster)
out <- st_sf(out, geom = st_geometry(x))

ctx_progress(ctx, 0.8, "writing")
rows <- ctx_write_layer(ctx, out, list(label = "text", value = "double precision", local_i = "double precision",
                                         p_value = "double precision", cluster = "text"))

classes <- list(c("High-High", "#d7191c"), c("Low-Low", "#2c7bb6"), c("High-Low", "#fdae61"),
                c("Low-High", "#abd9e9"), c("Not significant", "#f0f0f0"), c("No neighbours", "#bdbdbd"))
counts <- table(cluster)
present <- Filter(function(cl) cl[1] %in% names(counts), classes)
match <- c(list("match", list("get", "cluster")), unlist(lapply(present, function(cl) list(cl[1], cl[2])), recursive = FALSE), list("#f0f0f0"))

ctx_result(ctx, list(
  rows = rows,
  title = paste0("Clusters and outliers of ", field),
  properties = c("label", "value", "local_i", "p_value", "cluster"),
  style = list(kind = "maplibre", layers = list(
    list(type = "fill", paint = list(`fill-color` = match, `fill-opacity` = 0.85)),
    list(type = "line", paint = list(`line-color` = "#ffffff", `line-width` = 0.4)))),
  legend = list(type = "categorical", title = paste0("Local Moran's I: ", field, " (p < ", alpha, ")"),
                items = lapply(present, function(cl) list(label = cl[1], color = cl[2]))),
  popup = "{label}: {value} ({cluster}, p {p_value})",
  report = list(features = total, used = rows, skipped_null = total - rows, no_neighbours = no_neighbours,
                alpha = alpha, permutations = 999, seed = 12345,
                clusters = as.list(setNames(as.integer(counts), names(counts))),
                global_moran = list(I = unname(global$estimate[1]), expectation = unname(global$estimate[2]),
                                    p_value = global$p.value))
))
