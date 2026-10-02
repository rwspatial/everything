# What an R process gets (mirror of worker/ctx.py): inputs, reading a pub collection, writing its output, progress.
suppressPackageStartupMessages({ library(DBI); library(RPostgres); library(jsonlite); library(sf) })

ctx_open <- function() {
  con <- dbConnect(Postgres(), host = Sys.getenv("PGHOST"), port = as.integer(Sys.getenv("PGPORT", "5432")),
                   dbname = Sys.getenv("PGDATABASE"), user = Sys.getenv("PGUSER"), password = Sys.getenv("PGPASSWORD"))
  list(con = con, job_id = as.integer(Sys.getenv("JOB_ID")), table = paste0("job_", Sys.getenv("JOB_ID")),
       inputs = fromJSON(Sys.getenv("JOB_INPUTS"), simplifyVector = TRUE))
}

ctx_progress <- function(ctx, fraction, message = "") {
  invisible(dbExecute(ctx$con, "UPDATE app.jobs SET progress = $1, progress_message = $2 WHERE id = $3",
                      params = list(max(0, min(1, fraction)), substr(message, 1, 200), ctx$job_id)))
}

ctx_read_collection <- function(ctx, collection, fields) {
  stopifnot(grepl("^pub\\.[a-z0-9_]+$", collection), all(grepl("^[a-z_][a-z0-9_]*$", fields)))
  parts <- strsplit(collection, ".", fixed = TRUE)[[1]]
  g <- dbGetQuery(ctx$con, "SELECT a.attname FROM pg_attribute a JOIN pg_class c ON c.oid = a.attrelid
                             WHERE c.relnamespace = $1::regnamespace AND c.relname = $2 AND a.atttypid = 'geometry'::regtype
                               AND a.attnum > 0 AND NOT a.attisdropped ORDER BY a.attnum LIMIT 1",
                  params = list(parts[1], parts[2]))$attname
  cols <- paste(dbQuoteIdentifier(ctx$con, fields), collapse = ", ")
  q <- sprintf("SELECT id, %s, %s AS geom FROM %s WHERE %s IS NOT NULL ORDER BY id", cols,
               dbQuoteIdentifier(ctx$con, g), dbQuoteIdentifier(ctx$con, Id(schema = parts[1], table = parts[2])),
               dbQuoteIdentifier(ctx$con, g))
  st_read(ctx$con, query = q, geometry_column = "geom", quiet = TRUE)
}

# Write ml_out.job_<id>: id + columns (list(name = SQL type)) + geom (typed, SRID kept), with a GiST index.
ctx_write_layer <- function(ctx, x, columns) {
  srid <- st_crs(x)$epsg
  types <- unique(as.character(st_geometry_type(x)))
  gtype <- if (all(types %in% c("POLYGON", "MULTIPOLYGON"))) "MultiPolygon" else
           if (all(types %in% c("LINESTRING", "MULTILINESTRING"))) "MultiLineString" else
           if (all(types == "POINT")) "Point" else "Geometry"
  tbl <- dbQuoteIdentifier(ctx$con, Id(schema = "ml_out", table = ctx$table))
  defs <- paste(sprintf("%s %s", dbQuoteIdentifier(ctx$con, names(columns)), unlist(columns)), collapse = ", ")
  dbWithTransaction(ctx$con, {
    dbExecute(ctx$con, sprintf("DROP TABLE IF EXISTS %s", tbl))
    dbExecute(ctx$con, sprintf("CREATE TABLE %s (id integer PRIMARY KEY, %s, geom geometry(%s, %d))", tbl, defs, gtype, srid))
    wkb <- vapply(st_as_binary(st_geometry(x), hex = TRUE), as.character, "")
    geom <- if (startsWith(gtype, "Multi")) sprintf("ST_Multi(ST_GeomFromWKB(decode($%d, 'hex'), %d))", length(columns) + 2, srid)
            else sprintf("ST_GeomFromWKB(decode($%d, 'hex'), %d)", length(columns) + 2, srid)
    sql <- sprintf("INSERT INTO %s (id, %s, geom) VALUES ($1, %s, %s)", tbl,
                   paste(dbQuoteIdentifier(ctx$con, names(columns)), collapse = ", "),
                   paste(sprintf("$%d", seq_along(columns) + 1), collapse = ", "), geom)
    df <- st_drop_geometry(x)
    params <- c(list(as.integer(df$id)), lapply(names(columns), function(n) df[[n]]), list(wkb))
    dbExecute(ctx$con, sql, params = unname(params))
    dbExecute(ctx$con, sprintf("CREATE INDEX ON %s USING gist (geom)", tbl))
    dbExecute(ctx$con, sprintf("ANALYZE %s", tbl))
  })
  nrow(x)
}

ctx_result <- function(ctx, result) {
  cat("RESULT ", toJSON(result, auto_unbox = TRUE, null = "null", digits = NA), "\n", sep = "")
  dbDisconnect(ctx$con)
}
