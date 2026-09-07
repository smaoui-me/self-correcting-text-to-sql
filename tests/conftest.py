"""Tiny relational fixture: no network, API key, or downloaded DB required."""
import sqlite3
from contextlib import closing

import pytest
from src.database import Database


@pytest.fixture
def database(tmp_path):
    path = tmp_path / "fixture.db"
    with closing(sqlite3.connect(path)) as connection:
        connection.executescript("""
        CREATE TABLE Artist (ArtistId INTEGER PRIMARY KEY, Name TEXT);
        CREATE TABLE Album (AlbumId INTEGER PRIMARY KEY, Title TEXT, ArtistId INTEGER REFERENCES Artist);
        CREATE TABLE Genre (GenreId INTEGER PRIMARY KEY, Name TEXT);
        CREATE TABLE Employee (EmployeeId INTEGER PRIMARY KEY, FirstName TEXT, LastName TEXT);
        CREATE TABLE Customer (CustomerId INTEGER PRIMARY KEY, FirstName TEXT, LastName TEXT,
                               Email TEXT, SupportRepId INTEGER REFERENCES Employee);
        CREATE TABLE Invoice (InvoiceId INTEGER PRIMARY KEY, CustomerId INTEGER REFERENCES Customer,
                              InvoiceDate TEXT, BillingCountry TEXT, Total REAL);
        CREATE TABLE Track (TrackId INTEGER PRIMARY KEY, Name TEXT, AlbumId INTEGER REFERENCES Album,
                            GenreId INTEGER REFERENCES Genre, Milliseconds INTEGER);
        CREATE TABLE InvoiceLine (InvoiceLineId INTEGER PRIMARY KEY, InvoiceId INTEGER REFERENCES Invoice,
                                  TrackId INTEGER REFERENCES Track, UnitPrice REAL, Quantity INTEGER);
        CREATE TABLE Playlist (PlaylistId INTEGER PRIMARY KEY, Name TEXT);
        CREATE TABLE PlaylistTrack (PlaylistId INTEGER REFERENCES Playlist, TrackId INTEGER REFERENCES Track);
        INSERT INTO Artist VALUES (1, 'Alpha'), (2, 'Beta');
        INSERT INTO Album VALUES (1, 'First', 1), (2, 'Second', 2);
        INSERT INTO Genre VALUES (1, 'Rock'), (2, 'Jazz');
        INSERT INTO Employee VALUES (1, 'Sam', 'Rep');
        INSERT INTO Customer VALUES (1, 'Ana', 'A', 'a@example.test', 1),
                                    (2, 'Bob', 'B', 'b@example.test', 1),
                                    (3, 'Cara', 'C', 'c@example.test', 1);
        INSERT INTO Invoice VALUES (1, 1, '2024-01-01', 'USA', 6),
                                   (2, 2, '2024-02-01', 'Canada', 2),
                                   (3, 1, '2024-02-02', 'USA', 2);
        INSERT INTO Track VALUES (1, 'One', 1, 1, 60000), (2, 'Two', 1, 2, 120000),
                                 (3, 'Three', 2, 1, 180000);
        INSERT INTO InvoiceLine VALUES (1, 1, 1, 2, 2), (2, 1, 2, 2, 1),
                                       (3, 2, 2, 2, 1), (4, 3, 1, 2, 1);
        INSERT INTO Playlist VALUES (1, 'Mix'), (2, 'Empty');
        INSERT INTO PlaylistTrack VALUES (1, 1), (1, 2);
        """)
    return Database(path)
