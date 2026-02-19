--
-- PostgreSQL database dump
--

--restrict b9xjl1OeClhXMc0IhNwXp3ngerKS9PARZzBwXO4EmU458PRj1zWSYdxCPX1K1x6

-- Dumped from database version 16.11 (Ubuntu 16.11-0ubuntu0.24.04.1)
-- Dumped by pg_dump version 16.11 (Ubuntu 16.11-0ubuntu0.24.04.1)

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

--
-- Name: public; Type: SCHEMA; Schema: -; Owner: -
--

-- *not* creating schema, since initdb creates it


SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- Name: instance_settings; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.instance_settings (
    id smallint NOT NULL,
    settings jsonb DEFAULT '{}'::jsonb NOT NULL,
    "updatedAt" timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT instance_settings_singleton CHECK ((id = 1))
);


--
-- Name: instance_settings_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.instance_settings_id_seq
    AS smallint
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: instance_settings_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.instance_settings_id_seq OWNED BY public.instance_settings.id;


--
-- Name: project_shares; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.project_shares (
    id integer NOT NULL,
    "projectId" integer NOT NULL,
    "userId" integer NOT NULL,
    permission text DEFAULT 'full'::text NOT NULL,
    "createdAt" timestamp with time zone DEFAULT now() NOT NULL,
    "updatedAt" timestamp with time zone
);


--
-- Name: project_shares_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.project_shares_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: project_shares_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.project_shares_id_seq OWNED BY public.project_shares.id;


--
-- Name: projects; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.projects (
    id integer NOT NULL,
    name character varying NOT NULL,
    description character varying,
    status character varying,
    "ownerId" integer,
    "createdAt" timestamp with time zone DEFAULT now(),
    "updatedAt" timestamp with time zone
);


--
-- Name: projects_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.projects_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: projects_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.projects_id_seq OWNED BY public.projects.id;


--
-- Name: protocol_tag_assignments; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.protocol_tag_assignments (
    "protocolDbId" integer NOT NULL,
    "tagId" text NOT NULL,
    "createdAt" timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: protocol_tags; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.protocol_tags (
    id text NOT NULL,
    title text NOT NULL,
    description text,
    color text,
    "createdAt" timestamp with time zone DEFAULT now() NOT NULL,
    "updatedAt" timestamp with time zone,
    "projectId" integer NOT NULL
);


--
-- Name: protocols; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.protocols (
    id integer NOT NULL,
    "protocolId" character varying NOT NULL,
    "projectId" integer,
    "protocolClassName" character varying NOT NULL,
    params json,
    status character varying,
    "parentIds" integer[],
    "childIds" integer[],
    "createdAt" timestamp with time zone DEFAULT now(),
    "updatedAt" timestamp with time zone
);


--
-- Name: protocols_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.protocols_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: protocols_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.protocols_id_seq OWNED BY public.protocols.id;


--
-- Name: user_settings; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.user_settings (
    "userId" integer NOT NULL,
    settings jsonb DEFAULT '{}'::jsonb NOT NULL,
    "updatedAt" timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: users; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.users (
    id integer NOT NULL,
    email character varying NOT NULL,
    role character varying,
    "hashedPassword" character varying NOT NULL,
    "isActive" boolean,
    "firstName" character varying,
    "lastName" character varying,
    institution character varying,
    "isVerified" boolean,
    "verificationCode" character varying,
    phone character varying,
    "position" character varying,
    country character varying,
    city character varying,
    "postalCode" character varying
);


--
-- Name: users_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.users_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: users_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.users_id_seq OWNED BY public.users.id;


--
-- Name: instance_settings id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.instance_settings ALTER COLUMN id SET DEFAULT nextval('public.instance_settings_id_seq'::regclass);


--
-- Name: project_shares id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.project_shares ALTER COLUMN id SET DEFAULT nextval('public.project_shares_id_seq'::regclass);


--
-- Name: projects id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.projects ALTER COLUMN id SET DEFAULT nextval('public.projects_id_seq'::regclass);


--
-- Name: protocols id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.protocols ALTER COLUMN id SET DEFAULT nextval('public.protocols_id_seq'::regclass);


--
-- Name: users id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.users ALTER COLUMN id SET DEFAULT nextval('public.users_id_seq'::regclass);


--
-- Name: instance_settings instance_settings_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.instance_settings
    ADD CONSTRAINT instance_settings_pkey PRIMARY KEY (id);


--
-- Name: protocol_tag_assignments pk_protocol_tag_assignments; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.protocol_tag_assignments
    ADD CONSTRAINT pk_protocol_tag_assignments PRIMARY KEY ("protocolDbId", "tagId");


--
-- Name: project_shares project_shares_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.project_shares
    ADD CONSTRAINT project_shares_pkey PRIMARY KEY (id);


--
-- Name: projects projects_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.projects
    ADD CONSTRAINT projects_pkey PRIMARY KEY (id);


--
-- Name: protocol_tags protocol_tags_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.protocol_tags
    ADD CONSTRAINT protocol_tags_pkey PRIMARY KEY (id);


--
-- Name: protocols protocols_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.protocols
    ADD CONSTRAINT protocols_pkey PRIMARY KEY (id);


--
-- Name: protocols protocols_protocolId_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.protocols
    ADD CONSTRAINT "protocols_protocolId_key" UNIQUE ("protocolId");


--
-- Name: project_shares uq_project_shares_project_user; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.project_shares
    ADD CONSTRAINT uq_project_shares_project_user UNIQUE ("projectId", "userId");


--
-- Name: protocols uq_protocols_projectId_protocolId; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.protocols
    ADD CONSTRAINT "uq_protocols_projectId_protocolId" UNIQUE ("projectId", "protocolId");


--
-- Name: user_settings user_settings_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.user_settings
    ADD CONSTRAINT user_settings_pkey PRIMARY KEY ("userId");


--
-- Name: users users_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.users
    ADD CONSTRAINT users_pkey PRIMARY KEY (id);


--
-- Name: idx_protocol_tag_assignments_protocolDbId; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX "idx_protocol_tag_assignments_protocolDbId" ON public.protocol_tag_assignments USING btree ("protocolDbId");


--
-- Name: idx_protocol_tag_assignments_tagId; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX "idx_protocol_tag_assignments_tagId" ON public.protocol_tag_assignments USING btree ("tagId");


--
-- Name: idx_protocol_tags_projectid; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_protocol_tags_projectid ON public.protocol_tags USING btree ("projectId");


--
-- Name: ix_projects_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_projects_id ON public.projects USING btree (id);


--
-- Name: ix_protocols_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_protocols_id ON public.protocols USING btree (id);


--
-- Name: ix_users_email; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX ix_users_email ON public.users USING btree (email);


--
-- Name: ix_users_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_users_id ON public.users USING btree (id);


--
-- Name: ux_protocol_tags_project_lower_title; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX ux_protocol_tags_project_lower_title ON public.protocol_tags USING btree ("projectId", lower(title));


--
-- Name: protocol_tags fk_protocol_tags_projectid; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.protocol_tags
    ADD CONSTRAINT fk_protocol_tags_projectid FOREIGN KEY ("projectId") REFERENCES public.projects(id) ON DELETE CASCADE;


--
-- Name: project_shares project_shares_projectId_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.project_shares
    ADD CONSTRAINT "project_shares_projectId_fkey" FOREIGN KEY ("projectId") REFERENCES public.projects(id) ON DELETE CASCADE;


--
-- Name: project_shares project_shares_userId_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.project_shares
    ADD CONSTRAINT "project_shares_userId_fkey" FOREIGN KEY ("userId") REFERENCES public.users(id) ON DELETE CASCADE;


--
-- Name: projects projects_ownerId_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.projects
    ADD CONSTRAINT "projects_ownerId_fkey" FOREIGN KEY ("ownerId") REFERENCES public.users(id);


--
-- Name: protocol_tag_assignments protocol_tag_assignments_protocolDbId_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.protocol_tag_assignments
    ADD CONSTRAINT "protocol_tag_assignments_protocolDbId_fkey" FOREIGN KEY ("protocolDbId") REFERENCES public.protocols(id) ON DELETE CASCADE;


--
-- Name: protocol_tag_assignments protocol_tag_assignments_tagId_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.protocol_tag_assignments
    ADD CONSTRAINT "protocol_tag_assignments_tagId_fkey" FOREIGN KEY ("tagId") REFERENCES public.protocol_tags(id) ON DELETE CASCADE;


--
-- Name: protocols protocols_projectId_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.protocols
    ADD CONSTRAINT "protocols_projectId_fkey" FOREIGN KEY ("projectId") REFERENCES public.projects(id);


--
-- Name: user_settings user_settings_userId_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.user_settings
    ADD CONSTRAINT "user_settings_userId_fkey" FOREIGN KEY ("userId") REFERENCES public.users(id) ON DELETE CASCADE;


--
-- PostgreSQL database dump complete
--

--unrestrict b9xjl1OeClhXMc0IhNwXp3ngerKS9PARZzBwXO4EmU458PRj1zWSYdxCPX1K1x6

